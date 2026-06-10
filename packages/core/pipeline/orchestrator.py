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

from packages.adapters.cloudrun.jobs_dispatcher import CloudRunJobsDispatcher


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
        )
        self._pipeline_store.create(record)

        def _run() -> None:
            self._execute(
                record=pipeline_id,
                client_id=cid,
                steps=resolved_steps,
                eval_llm_mode=eval_llm_mode,
                eval_suite=eval_suite,
                force_empty_deploy=force_empty_deploy,
                drive_source_ids=drive_source_ids,
            )

        if self._sync_mode():
            _run()
            final = self._pipeline_store.get(cid, pipeline_id)
            assert final is not None
            return final

        self._executor.submit(_run)
        return record

    def get(self, client_id: str, pipeline_id: str) -> PipelineRunRecord | None:
        return self._pipeline_store.get(client_id, pipeline_id)

    def list_runs(self, client_id: str, *, limit: int = 20) -> list[PipelineRunRecord]:
        return self._pipeline_store.list_runs(client_id, limit=limit)

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
            try:
                step_result = self._run_step(
                    client_id=client_id,
                    step=step,
                    eval_llm_mode=eval_llm_mode,
                    eval_suite=eval_suite,
                    force_empty_deploy=force_empty_deploy,
                    drive_source_ids=drive_source_ids,
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
    ) -> PipelineStepResult:
        if self._cloud_run_dispatch_enabled():
            return self._run_step_via_cloud_run(
                client_id=client_id,
                step=step,
                eval_llm_mode=eval_llm_mode,
                eval_suite=eval_suite,
                force_empty_deploy=force_empty_deploy,
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

    def _run_step_via_cloud_run(
        self,
        *,
        client_id: str,
        step: PipelineStep,
        eval_llm_mode: str,
        eval_suite: str,
        force_empty_deploy: bool,
    ) -> PipelineStepResult:
        assert self._jobs_dispatcher is not None
        if step == PipelineStep.DEPLOY:
            return self._run_deploy_step(
                client_id=client_id,
                force_empty_deploy=force_empty_deploy,
                via_cloud_run=True,
            )

        job_type = {
            PipelineStep.DRIVE_SYNC: JobType.DRIVE_SYNC,
            PipelineStep.INGEST: JobType.INGEST,
            PipelineStep.EVAL: JobType.EVAL,
        }[step]
        job_id = f"job_{uuid.uuid4().hex[:12]}"
        execution = self._jobs_dispatcher.dispatch(
            job_type=job_type,
            client_id=client_id,
            job_id=job_id,
            eval_llm_mode=eval_llm_mode,
            eval_suite=eval_suite,
        )
        try:
            final_execution = self._jobs_dispatcher.wait_for_execution(execution)
        except TimeoutError as exc:
            return PipelineStepResult(
                step=step.value,
                status="failed",
                job_id=job_id,
                cloud_run_execution=execution,
                error=str(exc),
            )
        if not self._jobs_dispatcher.execution_succeeded(final_execution):
            return PipelineStepResult(
                step=step.value,
                status="failed",
                job_id=job_id,
                cloud_run_execution=execution,
                error="Cloud Run job execution failed.",
            )

        self._hydrate_after_cloud_step(client_id=client_id, step=step)
        result = self._load_step_result(client_id=client_id, step=step)
        if step == PipelineStep.INGEST and not force_empty_deploy:
            chunk_count = int(result.get("chunk_count") or 0)
            if chunk_count <= 0:
                return PipelineStepResult(
                    step=step.value,
                    status="failed",
                    job_id=job_id,
                    cloud_run_execution=execution,
                    result=result,
                    error="Ingest produced zero chunks; deploy blocked (set force_empty_deploy to override).",
                )
        if step == PipelineStep.EVAL:
            deploy_eligible = bool(result.get("deploy_eligible"))
            status_ok = str(result.get("status") or "") == "pass"
            if not status_ok or not deploy_eligible:
                return PipelineStepResult(
                    step=step.value,
                    status="failed",
                    job_id=job_id,
                    cloud_run_execution=execution,
                    result=result,
                    error="Eval did not pass or is not deploy_eligible.",
                )
        return PipelineStepResult(
            step=step.value,
            status="succeeded",
            job_id=job_id,
            cloud_run_execution=execution,
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
            execution = self._jobs_dispatcher.dispatch(
                job_type=JobType.DEPLOY,
                client_id=client_id,
                job_id=job_id,
            )
            try:
                final_execution = self._jobs_dispatcher.wait_for_execution(execution)
            except TimeoutError as exc:
                return PipelineStepResult(
                    step=PipelineStep.DEPLOY.value,
                    status="failed",
                    job_id=job_id,
                    cloud_run_execution=execution,
                    error=str(exc),
                )
            if not self._jobs_dispatcher.execution_succeeded(final_execution):
                return PipelineStepResult(
                    step=PipelineStep.DEPLOY.value,
                    status="failed",
                    job_id=job_id,
                    cloud_run_execution=execution,
                    error="Cloud Run deploy job execution failed.",
                )
            self._hydrate_after_cloud_step(client_id=client_id, step=PipelineStep.DEPLOY)
            manifest = read_active_manifest(active_manifest_path(self._clients_root, client_id))
            return PipelineStepResult(
                step=PipelineStep.DEPLOY.value,
                status="succeeded",
                job_id=job_id,
                cloud_run_execution=execution,
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
