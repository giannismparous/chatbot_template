from __future__ import annotations

import json
import os
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any, Callable

from packages.core.config.loader import TenantConfigLoader
from packages.core.eval.gate import check_deploy_gate
from packages.core.ingestion.manifest import read_active_manifest
from packages.core.ingestion.paths import active_manifest_path, ingest_report_path
from packages.core.jobs.models import JobRecord, JobStatus, JobType
from packages.core.pipeline.models import (
    PipelineRunRecord,
    PipelineStatus,
    PipelineStep,
    PipelineStepResult,
    resolve_pipeline_steps,
    utc_now,
)
from packages.core.eval.paths import latest_eval_report_path
from packages.core.ports.file_store import FileStore
from packages.core.ports.pipeline_store import PipelineStore
from packages.core.stack.factory import project_root
from packages.core.tenant.paths import safe_client_id

from packages.adapters.cloudrun.jobs_dispatcher import (
    CloudRunJobsDispatcher,
    DispatchResult,
    ExecutionOutcome,
)
from packages.core.pipeline.logging_util import pipeline_log
from packages.core.pipeline.stale import is_pipeline_stale, mark_pipeline_stale
from packages.core.pipeline.timeouts import step_timeout_seconds


class PipelineOrchestrator:
    def __init__(
        self,
        *,
        pipeline_store: PipelineStore,
        job_runner: Any,
        clients_root: Path,
        file_store: FileStore | None = None,
        jobs_dispatcher: CloudRunJobsDispatcher | None = None,
    ) -> None:
        self._pipeline_store = pipeline_store
        self._job_runner = job_runner
        self._clients_root = clients_root
        self._file_store = file_store
        self._jobs_dispatcher = jobs_dispatcher
        self._executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="pipeline")

    def _sync_mode(self) -> bool:
        return os.getenv("ADMIN_JOBS_SYNC", "false").strip().lower() in {"1", "true", "yes", "on"}

    def _cloud_run_dispatch_enabled(self) -> bool:
        disabled = os.getenv("CLOUD_RUN_JOBS_DISABLED", "").strip().lower() in {
            "1",
            "true",
            "yes",
            "on",
        }
        return not disabled and self._jobs_dispatcher is not None

    def _durable_runner_enabled(self) -> bool:
        return self._cloud_run_dispatch_enabled()

    def start(
        self,
        *,
        client_id: str,
        preset: str | None = None,
        steps: list[str] | None = None,
        eval_llm_mode: str = "live",
        eval_suite: str = "full",
        force_empty_deploy: bool = False,
        drive_source_ids: list[str] | None = None,
    ) -> PipelineRunRecord:
        cid = safe_client_id(client_id)
        resolved_steps = resolve_pipeline_steps(preset=preset, steps=steps)
        pipeline_id = f"pipe_{uuid.uuid4().hex[:12]}"
        now = utc_now()
        manifest = read_active_manifest(active_manifest_path(self._clients_root, cid))
        record = PipelineRunRecord(
            pipeline_id=pipeline_id,
            client_id=cid,
            status=PipelineStatus.PENDING,
            preset=preset,
            steps=[step.value for step in resolved_steps],
            current_step=None,
            created_at=now,
            updated_at=now,
            active_version_before=manifest.active,
            index_manifest=manifest.to_dict(),
            force_empty_deploy=force_empty_deploy,
            eval_llm_mode=eval_llm_mode,
            eval_suite=eval_suite,
            drive_source_ids=drive_source_ids,
        )
        self._pipeline_store.create(record)

        if self._sync_mode():
            self.execute_pipeline(client_id=cid, pipeline_id=pipeline_id)
            final = self._pipeline_store.get(cid, pipeline_id)
            assert final is not None
            return final

        if self._durable_runner_enabled():
            self._dispatch_pipeline_runner(record)
            return record

        self._executor.submit(
            lambda: self.execute_pipeline(client_id=cid, pipeline_id=pipeline_id)
        )
        return record

    def _dispatch_pipeline_runner(self, record: PipelineRunRecord) -> None:
        assert self._jobs_dispatcher is not None
        dispatch = self._jobs_dispatcher.dispatch_pipeline_with_meta(
            client_id=record.client_id,
            pipeline_id=record.pipeline_id,
        )
        record.runner_execution = dispatch.execution_name
        record.status = PipelineStatus.RUNNING
        record.started_at = utc_now()
        self._save(record)
        pipeline_log(
            f"dispatched pipeline runner client={record.client_id} pipeline_id={record.pipeline_id} "
            f"operation={dispatch.operation_name} execution={dispatch.execution_name}"
        )

    def execute_pipeline(self, *, client_id: str, pipeline_id: str) -> PipelineRunRecord:
        current = self._pipeline_store.get(client_id, pipeline_id)
        if current is None:
            raise ValueError(f"Pipeline run not found: {pipeline_id}")
        pipeline_log(
            f"execute_pipeline start client={client_id} pipeline_id={pipeline_id} "
            f"steps={current.steps} preset={current.preset}"
        )
        resolved_steps = [PipelineStep(step) for step in current.steps]
        self._execute(
            record=pipeline_id,
            client_id=client_id,
            steps=resolved_steps,
            eval_llm_mode=current.eval_llm_mode,
            eval_suite=current.eval_suite,
            force_empty_deploy=current.force_empty_deploy,
            drive_source_ids=current.drive_source_ids,
        )
        final = self._pipeline_store.get(client_id, pipeline_id)
        assert final is not None
        pipeline_log(
            f"execute_pipeline finished client={client_id} pipeline_id={pipeline_id} "
            f"status={final.status.value} steps_completed={len(final.step_results)}"
        )
        return final

    def _heartbeat(self, client_id: str, pipeline_id: str) -> None:
        current = self._pipeline_store.get(client_id, pipeline_id)
        if current is not None:
            self._save(current)

    def get(self, client_id: str, pipeline_id: str) -> PipelineRunRecord | None:
        return self._pipeline_store.get(client_id, pipeline_id)

    def get_resolved(self, client_id: str, pipeline_id: str) -> PipelineRunRecord | None:
        record = self._pipeline_store.get(client_id, pipeline_id)
        if record is None:
            return None
        if is_pipeline_stale(record):
            record = mark_pipeline_stale(record)
            self._save(record)
        return record

    def mark_failed(
        self,
        client_id: str,
        pipeline_id: str,
        *,
        reason: str,
    ) -> PipelineRunRecord:
        record = self._pipeline_store.get(client_id, pipeline_id)
        if record is None:
            raise ValueError(f"Pipeline run not found: {pipeline_id}")
        if record.status not in {PipelineStatus.PENDING, PipelineStatus.RUNNING, PipelineStatus.STALE}:
            raise ValueError(
                f"Cannot mark pipeline failed from status={record.status.value!r}."
            )
        record.status = PipelineStatus.FAILED
        record.error = reason
        record.finished_at = utc_now()
        record.current_step = None
        self._save(record)
        return record

    def list_runs(self, client_id: str, *, limit: int = 20) -> list[PipelineRunRecord]:
        records = self._pipeline_store.list_runs(client_id, limit=limit)
        resolved: list[PipelineRunRecord] = []
        for record in records:
            if is_pipeline_stale(record):
                record = mark_pipeline_stale(record)
                self._save(record)
            resolved.append(record)
        return resolved

    def _save(self, record: PipelineRunRecord) -> None:
        record.updated_at = utc_now()
        self._pipeline_store.update(record)

    def _execute(
        self,
        *,
        record: str,
        client_id: str,
        steps: list[PipelineStep],
        eval_llm_mode: str,
        eval_suite: str,
        force_empty_deploy: bool,
        drive_source_ids: list[str] | None,
    ) -> None:
        pipeline_id = record
        current = self._pipeline_store.get(client_id, pipeline_id)
        if current is None:
            return
        current.status = PipelineStatus.RUNNING
        current.started_at = utc_now()
        self._save(current)

        for step in steps:
            current = self._pipeline_store.get(client_id, pipeline_id)
            if current is None:
                return
            current.current_step = step.value
            self._save(current)
            pipeline_log(
                f"pipeline step start client={client_id} pipeline_id={pipeline_id} step={step.value}"
            )
            try:
                step_result = self._run_step(
                    client_id=client_id,
                    step=step,
                    eval_llm_mode=eval_llm_mode,
                    eval_suite=eval_suite,
                    force_empty_deploy=force_empty_deploy,
                    drive_source_ids=drive_source_ids,
                    pipeline_id=pipeline_id,
                )
            except Exception as exc:
                current = self._pipeline_store.get(client_id, pipeline_id)
                if current is None:
                    return
                current.status = PipelineStatus.FAILED
                current.finished_at = utc_now()
                current.error = str(exc)
                current.step_results.append(
                    PipelineStepResult(step=step.value, status="failed", error=str(exc))
                )
                self._refresh_manifest(current)
                self._save(current)
                return

            current = self._pipeline_store.get(client_id, pipeline_id)
            if current is None:
                return
            current.step_results.append(step_result)
            self._apply_step_side_effects(current, step, step_result)
            self._refresh_manifest(current)
            self._save(current)
            pipeline_log(
                f"pipeline step persisted client={client_id} pipeline_id={pipeline_id} "
                f"step={step.value} status={step_result.status} "
                f"step_results_count={len(current.step_results)}"
            )

            if step_result.status != "succeeded":
                current.status = PipelineStatus.FAILED
                current.finished_at = utc_now()
                current.error = step_result.error or f"Step {step.value} failed"
                self._save(current)
                return

        current = self._pipeline_store.get(client_id, pipeline_id)
        if current is None:
            return
        current.status = PipelineStatus.SUCCEEDED
        current.current_step = None
        current.finished_at = utc_now()
        if PipelineStep.DEPLOY.value in current.steps:
            current.runtime_refresh_note = (
                "Deploy completed. Restart the Cloud Run API service (or call reload_runtime) "
                "so chat retrieval hydrates the new active index."
            )
        self._save(current)

    def _refresh_manifest(self, record: PipelineRunRecord) -> None:
        manifest = read_active_manifest(active_manifest_path(self._clients_root, record.client_id))
        record.index_manifest = manifest.to_dict()

    def _apply_step_side_effects(
        self,
        record: PipelineRunRecord,
        step: PipelineStep,
        step_result: PipelineStepResult,
    ) -> None:
        if step == PipelineStep.INGEST:
            record.pending_version_after_ingest = step_result.result.get("version_id")
            record.ingest_summary = {
                "version_id": step_result.result.get("version_id"),
                "sources_total": step_result.result.get("source_count"),
                "indexed": step_result.result.get("indexed_count"),
                "chunks_total": step_result.result.get("chunk_count"),
            }
            version_id = step_result.result.get("version_id")
            if version_id:
                report_path = ingest_report_path(self._clients_root, record.client_id, str(version_id))
                if report_path.is_file():
                    payload = json.loads(report_path.read_text(encoding="utf-8"))
                    if isinstance(payload, dict):
                        record.ingest_summary.update(
                            {
                                "sources_total": payload.get("sources_total"),
                                "indexed": payload.get("indexed"),
                                "chunks_total": payload.get("chunks_total"),
                            }
                        )
        if step == PipelineStep.EVAL:
            record.eval_summary = {
                "run_id": step_result.result.get("run_id"),
                "status": step_result.result.get("status"),
                "deploy_eligible": step_result.result.get("deploy_eligible"),
                "evaluated_index_version": step_result.result.get("evaluated_index_version"),
            }
        if step == PipelineStep.DEPLOY:
            record.active_version_after_deploy = step_result.result.get("activated_version")

    def _run_step(
        self,
        *,
        client_id: str,
        step: PipelineStep,
        eval_llm_mode: str,
        eval_suite: str,
        force_empty_deploy: bool,
        drive_source_ids: list[str] | None,
        pipeline_id: str | None = None,
    ) -> PipelineStepResult:
        if self._cloud_run_dispatch_enabled():
            return self._run_step_via_cloud_run(
                client_id=client_id,
                step=step,
                eval_llm_mode=eval_llm_mode,
                eval_suite=eval_suite,
                force_empty_deploy=force_empty_deploy,
                pipeline_id=pipeline_id,
            )
        if step == PipelineStep.DEPLOY:
            return self._run_deploy_step(
                client_id=client_id,
                force_empty_deploy=force_empty_deploy,
            )
        job_type = {
            PipelineStep.DRIVE_SYNC: JobType.DRIVE_SYNC,
            PipelineStep.INGEST: JobType.INGEST,
            PipelineStep.EVAL: JobType.EVAL,
        }[step]
        runner = self._build_runner(
            client_id=client_id,
            step=step,
            eval_llm_mode=eval_llm_mode,
            eval_suite=eval_suite,
            drive_source_ids=drive_source_ids,
        )
        submitted = self._job_runner.submit(client_id=client_id, job_type=job_type, runner=runner)
        final = submitted if submitted.status in {JobStatus.SUCCEEDED, JobStatus.FAILED} else self._wait_for_job(
            client_id, submitted.job_id
        )
        if step == PipelineStep.INGEST and not force_empty_deploy:
            chunk_count = int(final.result.get("chunk_count") or 0)
            if chunk_count <= 0:
                return PipelineStepResult(
                    step=step.value,
                    status="failed",
                    job_id=final.job_id,
                    result=final.result,
                    error="Ingest produced zero chunks; deploy blocked (set force_empty_deploy to override).",
                )
        if step == PipelineStep.EVAL:
            deploy_eligible = bool(final.result.get("deploy_eligible"))
            status_ok = str(final.result.get("status") or "") == "pass"
            if not status_ok or not deploy_eligible:
                return PipelineStepResult(
                    step=step.value,
                    status="failed",
                    job_id=final.job_id,
                    result=final.result,
                    error="Eval did not pass or is not deploy_eligible.",
                )
        status = "succeeded" if final.status == JobStatus.SUCCEEDED else "failed"
        return PipelineStepResult(
            step=step.value,
            status=status,
            job_id=final.job_id,
            result=final.result,
            error=final.error,
        )

    def _step_result_from_execution(
        self,
        *,
        step: PipelineStep,
        job_id: str,
        dispatch: DispatchResult,
        execution: dict[str, Any],
        status: str,
        result: dict[str, Any] | None = None,
        error: str | None = None,
    ) -> PipelineStepResult:
        meta = self._jobs_dispatcher.execution_meta(execution) if self._jobs_dispatcher else {}
        meta.update(
            {
                "job_name": dispatch.job_name,
                "region": dispatch.region,
                "operation_name": dispatch.operation_name,
            }
        )
        execution_name = str(execution.get("name") or dispatch.execution_name or "")
        return PipelineStepResult(
            step=step.value,
            status=status,
            job_id=job_id,
            cloud_run_execution=execution_name or None,
            result=result or {},
            error=error,
            execution_meta=meta,
        )

    def _run_step_via_cloud_run(
        self,
        *,
        client_id: str,
        step: PipelineStep,
        eval_llm_mode: str,
        eval_suite: str,
        force_empty_deploy: bool,
        pipeline_id: str | None = None,
    ) -> PipelineStepResult:
        assert self._jobs_dispatcher is not None
        if step == PipelineStep.DEPLOY:
            return self._run_deploy_step(
                client_id=client_id,
                force_empty_deploy=force_empty_deploy,
                via_cloud_run=True,
                pipeline_id=pipeline_id,
            )

        job_type = {
            PipelineStep.DRIVE_SYNC: JobType.DRIVE_SYNC,
            PipelineStep.INGEST: JobType.INGEST,
            PipelineStep.EVAL: JobType.EVAL,
        }[step]
        job_id = f"job_{uuid.uuid4().hex[:12]}"
        timeout = float(step_timeout_seconds(step))
        job_name = self._jobs_dispatcher.job_name(job_type)
        pipeline_log(
            f"dispatch child step={step.value} job={job_name} client={client_id} "
            f"job_id={job_id} timeout={int(timeout)}s"
        )
        dispatch = self._jobs_dispatcher.dispatch_with_meta(
            job_type=job_type,
            client_id=client_id,
            job_id=job_id,
            eval_llm_mode=eval_llm_mode,
            eval_suite=eval_suite,
        )
        execution_name = dispatch.execution_name or ""
        pipeline_log(
            f"child dispatch returned operation={dispatch.operation_name} "
            f"execution={execution_name}"
        )

        def _on_poll(execution: dict[str, Any], outcome: ExecutionOutcome) -> None:
            if pipeline_id is not None:
                self._heartbeat(client_id, pipeline_id)
            pipeline_log(
                f"child poll step={step.value} execution={execution.get('name')} "
                f"outcome={outcome.value}"
            )

        try:
            final_execution = self._jobs_dispatcher.wait_for_execution(
                execution_name,
                timeout_seconds=timeout,
                on_poll=_on_poll,
            )
        except TimeoutError as exc:
            pipeline_log(f"child step timeout step={step.value} execution={execution_name}")
            return self._step_result_from_execution(
                step=step,
                job_id=job_id,
                dispatch=dispatch,
                execution={"name": execution_name, "completionStatus": "EXECUTION_FAILED"},
                status="failed",
                error=str(exc),
            )
        outcome = self._jobs_dispatcher.execution_outcome(final_execution)
        if outcome != ExecutionOutcome.SUCCEEDED:
            pipeline_log(
                f"child step failed step={step.value} outcome={outcome.value} "
                f"detail={self._jobs_dispatcher.execution_failure_detail(final_execution)}"
            )
            return self._step_result_from_execution(
                step=step,
                job_id=job_id,
                dispatch=dispatch,
                execution=final_execution,
                status="failed",
                error=self._jobs_dispatcher.execution_failure_detail(final_execution),
            )

        pipeline_log(f"child step succeeded step={step.value}; hydrating outputs")
        self._hydrate_after_cloud_step(client_id=client_id, step=step)
        result = self._load_step_result(client_id=client_id, step=step)
        pipeline_log(f"child step loaded result step={step.value} keys={','.join(sorted(result.keys()))}")
        if step == PipelineStep.INGEST and not force_empty_deploy:
            chunk_count = int(result.get("chunk_count") or 0)
            if chunk_count <= 0:
                return self._step_result_from_execution(
                    step=step,
                    job_id=job_id,
                    dispatch=dispatch,
                    execution=final_execution,
                    status="failed",
                    result=result,
                    error="Ingest produced zero chunks; deploy blocked (set force_empty_deploy to override).",
                )
        if step == PipelineStep.EVAL:
            deploy_eligible = bool(result.get("deploy_eligible"))
            status_ok = str(result.get("status") or "") == "pass"
            if not status_ok or not deploy_eligible:
                return self._step_result_from_execution(
                    step=step,
                    job_id=job_id,
                    dispatch=dispatch,
                    execution=final_execution,
                    status="failed",
                    result=result,
                    error="Eval did not pass or is not deploy_eligible.",
                )
        return self._step_result_from_execution(
            step=step,
            job_id=job_id,
            dispatch=dispatch,
            execution=final_execution,
            status="succeeded",
            result=result,
        )

    def _hydrate_after_cloud_step(self, *, client_id: str, step: PipelineStep) -> None:
        from packages.adapters.storage.gcs_file_store import GcsFileStore

        if not isinstance(self._file_store, GcsFileStore):
            return
        if step == PipelineStep.DRIVE_SYNC:
            from packages.core.storage.drive_cache_hydrator import hydrate_client_drive_cache

            hydrate_client_drive_cache(client_id=client_id, file_store=self._file_store, force=True)
            return
        if step in {PipelineStep.INGEST, PipelineStep.EVAL, PipelineStep.DEPLOY}:
            from packages.core.storage.tenant_cache_hydrator import hydrate_client_index_state

            hydrate_client_index_state(client_id=client_id, file_store=self._file_store, force=True)
        if step == PipelineStep.EVAL:
            from packages.core.storage.eval_output_sync import hydrate_client_eval_report

            hydrate_client_eval_report(client_id=client_id, file_store=self._file_store, force=True)

    def _load_step_result(self, *, client_id: str, step: PipelineStep) -> dict[str, Any]:
        if step == PipelineStep.DRIVE_SYNC:
            return {"status": "succeeded"}
        if step == PipelineStep.INGEST:
            manifest = read_active_manifest(active_manifest_path(self._clients_root, client_id))
            result: dict[str, Any] = {"version_id": manifest.pending}
            if manifest.pending:
                report_path = ingest_report_path(self._clients_root, client_id, manifest.pending)
                if report_path.is_file():
                    report = json.loads(report_path.read_text(encoding="utf-8"))
                    if isinstance(report, dict):
                        result.update(
                            {
                                "source_count": report.get("sources_total"),
                                "indexed_count": report.get("indexed"),
                                "chunk_count": report.get("chunks_total"),
                            }
                        )
            return result
        if step == PipelineStep.EVAL:
            path = latest_eval_report_path(self._clients_root, client_id)
            if not path.is_file():
                return {}
            report = json.loads(path.read_text(encoding="utf-8"))
            if not isinstance(report, dict):
                return {}
            return {
                "run_id": report.get("run_id"),
                "status": report.get("status"),
                "deploy_eligible": report.get("deploy_eligible"),
                "evaluated_index_version": report.get("evaluated_index_version"),
                "report_path": str(path),
            }
        return {}

    def _run_deploy_step(
        self,
        *,
        client_id: str,
        force_empty_deploy: bool,
        via_cloud_run: bool = False,
        pipeline_id: str | None = None,
    ) -> PipelineStepResult:
        if via_cloud_run:
            self._hydrate_after_cloud_step(client_id=client_id, step=PipelineStep.INGEST)
            self._hydrate_after_cloud_step(client_id=client_id, step=PipelineStep.EVAL)
        loader = TenantConfigLoader(
            clients_root=self._clients_root,
            domain_packs_root=project_root() / "packages" / "domain_packs",
        )
        gate = check_deploy_gate(
            clients_root=self._clients_root,
            client_id=client_id,
            config_loader=loader,
        )
        if not gate.allowed:
            return PipelineStepResult(
                step=PipelineStep.DEPLOY.value,
                status="failed",
                error=f"Deploy gate blocked ({gate.reason}): {gate.detail}",
            )
        manifest = read_active_manifest(active_manifest_path(self._clients_root, client_id))
        if manifest.pending and not force_empty_deploy:
            report_path = ingest_report_path(self._clients_root, client_id, manifest.pending)
            if report_path.is_file():
                report = json.loads(report_path.read_text(encoding="utf-8"))
                chunks_total = int((report or {}).get("chunks_total") or 0)
                if chunks_total <= 0:
                    return PipelineStepResult(
                        step=PipelineStep.DEPLOY.value,
                        status="failed",
                        error="Pending index has chunks_total=0; deploy blocked.",
                    )

        if via_cloud_run and self._jobs_dispatcher is not None:
            job_id = f"job_{uuid.uuid4().hex[:12]}"
            timeout = float(step_timeout_seconds(PipelineStep.DEPLOY))
            dispatch = self._jobs_dispatcher.dispatch_with_meta(
                job_type=JobType.DEPLOY,
                client_id=client_id,
                job_id=job_id,
            )
            execution_name = dispatch.execution_name or ""

            def _on_poll(execution: dict[str, Any], outcome: ExecutionOutcome) -> None:
                if pipeline_id is not None:
                    self._heartbeat(client_id, pipeline_id)
                pipeline_log(
                    f"child poll step=deploy execution={execution.get('name')} outcome={outcome.value}"
                )

            try:
                final_execution = self._jobs_dispatcher.wait_for_execution(
                    execution_name,
                    timeout_seconds=timeout,
                    on_poll=_on_poll,
                )
            except TimeoutError as exc:
                return self._step_result_from_execution(
                    step=PipelineStep.DEPLOY,
                    job_id=job_id,
                    dispatch=dispatch,
                    execution={"name": execution_name},
                    status="failed",
                    error=str(exc),
                )
            if not self._jobs_dispatcher.execution_succeeded(final_execution):
                return self._step_result_from_execution(
                    step=PipelineStep.DEPLOY,
                    job_id=job_id,
                    dispatch=dispatch,
                    execution=final_execution,
                    status="failed",
                    error=self._jobs_dispatcher.execution_failure_detail(final_execution),
                )
            self._hydrate_after_cloud_step(client_id=client_id, step=PipelineStep.DEPLOY)
            manifest = read_active_manifest(active_manifest_path(self._clients_root, client_id))
            return self._step_result_from_execution(
                step=PipelineStep.DEPLOY,
                job_id=job_id,
                dispatch=dispatch,
                execution=final_execution,
                status="succeeded",
                result={
                    "activated_version": manifest.active,
                    "eval_run_id": gate.report.run_id if gate.report else None,
                },
            )

        from apps.worker.jobs.deploy_index import deploy_index

        activated = deploy_index(clients_root=self._clients_root, client_id=client_id)
        return PipelineStepResult(
            step=PipelineStep.DEPLOY.value,
            status="succeeded",
            result={
                "activated_version": activated,
                "eval_run_id": gate.report.run_id if gate.report else None,
            },
        )

    def _wait_for_job(self, client_id: str, job_id: str, *, timeout_seconds: float = 7200) -> JobRecord:
        deadline = time.time() + timeout_seconds
        while time.time() < deadline:
            record = self._job_runner.get_job(client_id, job_id)
            if record is None:
                raise RuntimeError(f"Job record missing: {job_id}")
            if record.status in {JobStatus.SUCCEEDED, JobStatus.FAILED}:
                return record
            time.sleep(1.0)
        raise TimeoutError(f"Timed out waiting for job {job_id}")

    def _build_runner(
        self,
        *,
        client_id: str,
        step: PipelineStep,
        eval_llm_mode: str,
        eval_suite: str,
        drive_source_ids: list[str] | None,
    ) -> Callable[[], dict[str, Any]]:
        root = self._clients_root

        if step == PipelineStep.DRIVE_SYNC:
            def _drive_sync() -> dict[str, Any]:
                from packages.core.drive_sources.service import sync_client_drive_sources

                loader = TenantConfigLoader(
                    clients_root=root,
                    domain_packs_root=project_root() / "packages" / "domain_packs",
                )
                return sync_client_drive_sources(
                    clients_root=root,
                    client_id=client_id,
                    config_loader=loader,
                    source_ids=drive_source_ids,
                )

            return _drive_sync

        if step == PipelineStep.INGEST:
            def _ingest() -> dict[str, Any]:
                from packages.core.ingestion.pipeline import ingest_client_uploads

                loader = TenantConfigLoader(
                    clients_root=root,
                    domain_packs_root=project_root() / "packages" / "domain_packs",
                )
                result = ingest_client_uploads(
                    clients_root=root,
                    client_id=client_id,
                    config_loader=loader,
                )
                return {
                    "version_id": result.version_id,
                    "chunk_count": result.chunk_count,
                    "source_count": result.source_count,
                    "indexed_count": result.indexed_count,
                }

            return _ingest

        if step == PipelineStep.EVAL:
            def _eval() -> dict[str, Any]:
                from packages.core.eval.runner import run_eval

                report, run_dir = run_eval(
                    clients_root=root,
                    client_id=client_id,
                    suite_filter=eval_suite,
                    llm_mode=eval_llm_mode,
                )
                return {
                    "run_id": report.run_id,
                    "status": report.status,
                    "deploy_eligible": report.deploy_eligible,
                    "evaluated_index_version": report.evaluated_index_version,
                    "report_path": str(run_dir / "eval_report.json"),
                }

            return _eval

        raise ValueError(f"Unsupported pipeline step: {step}")
