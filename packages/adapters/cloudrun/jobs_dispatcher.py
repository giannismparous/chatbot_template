from __future__ import annotations

import json
import logging
import os
import subprocess
import time
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable

import google.auth
from google.auth.transport.requests import Request as GoogleAuthRequest

from packages.core.jobs.models import JobType
from packages.core.pipeline.logging_util import pipeline_log

logger = logging.getLogger(__name__)

_JOB_TYPE_CLI: dict[JobType, str] = {
    JobType.DRIVE_SYNC: "drive-sync",
    JobType.INGEST: "ingest",
    JobType.EVAL: "eval",
    JobType.DEPLOY: "deploy",
    JobType.PIPELINE: "pipeline",
}


class ExecutionOutcome(str, Enum):
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    CANCELLED = "cancelled"
    TIMEOUT = "timeout"
    UNKNOWN = "unknown"


@dataclass
class DispatchResult:
    job_type: JobType
    job_name: str
    region: str
    client_id: str
    operation_name: str | None = None
    execution_name: str | None = None
    raw_run_response: dict[str, Any] = field(default_factory=dict)


class CloudRunJobsDispatcher:
    """Dispatch Cloud Run Jobs via REST API (ADC). gcloud remains dev fallback."""

    def __init__(
        self,
        *,
        project: str,
        region: str,
        job_prefix: str = "chatbot",
    ) -> None:
        self._project = project.strip()
        self._region = region.strip() or "europe-west1"
        self._job_prefix = job_prefix.strip() or "chatbot"
        if not self._project:
            raise ValueError("GOOGLE_CLOUD_PROJECT is required for Cloud Run job dispatch.")

    @property
    def region(self) -> str:
        return self._region

    @property
    def project(self) -> str:
        return self._project

    def job_name(self, job_type: JobType) -> str:
        return f"{self._job_prefix}-{job_type.value.replace('_', '-')}"

    @staticmethod
    def _is_execution_name(name: str) -> bool:
        return "/executions/" in name

    @staticmethod
    def _is_operation_name(name: str) -> bool:
        return "/operations/" in name

    def _auth_token(self) -> str:
        credentials, _ = google.auth.default(
            scopes=["https://www.googleapis.com/auth/cloud-platform"]
        )
        credentials.refresh(GoogleAuthRequest())
        return credentials.token

    def _api_get(self, resource_name: str) -> dict[str, Any]:
        url = f"https://run.googleapis.com/v2/{resource_name.lstrip('/')}"
        request = urllib.request.Request(
            url,
            method="GET",
            headers={"Authorization": f"Bearer {self._auth_token()}"},
        )
        try:
            with urllib.request.urlopen(request, timeout=60) as response:
                data = json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")
            raise RuntimeError(
                f"Cloud Run GET failed for {resource_name}: HTTP {exc.code} {detail}"
            ) from exc
        return data if isinstance(data, dict) else {}

    def _api_post(self, url: str, body: dict[str, Any]) -> dict[str, Any]:
        payload = json.dumps(body).encode("utf-8")
        request = urllib.request.Request(
            url,
            data=payload,
            method="POST",
            headers={
                "Authorization": f"Bearer {self._auth_token()}",
                "Content-Type": "application/json",
            },
        )
        try:
            with urllib.request.urlopen(request, timeout=60) as response:
                data = json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")
            raise RuntimeError(f"Cloud Run POST failed for {url}: HTTP {exc.code} {detail}") from exc
        return data if isinstance(data, dict) else {}

    def get_execution(self, execution_name: str) -> dict[str, Any]:
        if self._is_operation_name(execution_name):
            pipeline_log(f"get_execution received operation name; resolving: {execution_name}")
            operation = self.wait_for_operation(
                execution_name,
                timeout_seconds=self._operation_timeout_seconds(),
            )
            resolved = self._execution_name_from_operation(operation)
            if not resolved:
                raise RuntimeError(
                    f"Operation completed but no execution name found: {execution_name}"
                )
            execution_name = resolved
        return self._api_get(execution_name)

    def wait_for_operation(
        self,
        operation_name: str,
        *,
        timeout_seconds: float = 300,
        poll_interval_seconds: float = 2.0,
    ) -> dict[str, Any]:
        deadline = time.time() + timeout_seconds
        pipeline_log(f"polling operation={operation_name} timeout={int(timeout_seconds)}s")
        while time.time() < deadline:
            operation = self._api_get(operation_name)
            done = bool(operation.get("done"))
            pipeline_log(
                f"operation poll done={done} name={operation_name} "
                f"keys={','.join(sorted(operation.keys()))}"
            )
            if done:
                if operation.get("error"):
                    raise RuntimeError(
                        f"Cloud Run operation failed: {json.dumps(operation.get('error'))}"
                    )
                return operation
            time.sleep(poll_interval_seconds)
        raise TimeoutError(f"Timed out waiting for Cloud Run operation {operation_name}")

    @staticmethod
    def _execution_name_from_operation(operation: dict[str, Any]) -> str:
        response = operation.get("response")
        if isinstance(response, dict):
            name = str(response.get("name") or "")
            if CloudRunJobsDispatcher._is_execution_name(name):
                return name
        metadata = operation.get("metadata")
        if isinstance(metadata, dict):
            name = str(metadata.get("name") or "")
            if CloudRunJobsDispatcher._is_execution_name(name):
                return name
        return ""

    def resolve_run_response(
        self,
        *,
        job_type: JobType,
        run_response: dict[str, Any],
    ) -> DispatchResult:
        job_name = self.job_name(job_type)
        name = str(run_response.get("name") or "")
        result = DispatchResult(
            job_type=job_type,
            job_name=job_name,
            region=self._region,
            client_id="",
            raw_run_response=run_response,
        )
        pipeline_log(
            f"jobs.run raw response name={name!r} keys={','.join(sorted(run_response.keys()))}"
        )
        if self._is_execution_name(name):
            result.execution_name = name
            pipeline_log(f"jobs.run returned execution directly: {name}")
            return result
        if self._is_operation_name(name) or "done" in run_response:
            result.operation_name = name
            pipeline_log(f"jobs.run returned operation; polling: {name}")
            operation = self.wait_for_operation(
                name,
                timeout_seconds=self._operation_timeout_seconds(),
            )
            result.raw_run_response = operation
            execution_name = self._execution_name_from_operation(operation)
            if execution_name:
                result.execution_name = execution_name
                pipeline_log(f"operation resolved execution={execution_name}")
                return result
        metadata = run_response.get("metadata")
        if isinstance(metadata, dict):
            meta_name = str(metadata.get("name") or "")
            if self._is_execution_name(meta_name):
                result.execution_name = meta_name
                pipeline_log(f"run response metadata execution={meta_name}")
                return result
        raise RuntimeError(
            f"Could not resolve execution from jobs.run response for {job_name}: "
            f"{json.dumps(run_response)[:800]}"
        )

    def _operation_timeout_seconds(self) -> float:
        raw = os.getenv("CLOUD_RUN_OPERATION_TIMEOUT_SECONDS", "300").strip()
        try:
            return max(30.0, float(raw))
        except ValueError:
            return 300.0

    def list_latest_execution(self, job_type: JobType) -> str | None:
        job_name = self.job_name(job_type)
        parent = (
            f"projects/{self._project}/locations/{self._region}/jobs/{job_name}/executions"
        )
        url = f"https://run.googleapis.com/v2/{parent}?pageSize=1"
        request = urllib.request.Request(
            url,
            method="GET",
            headers={"Authorization": f"Bearer {self._auth_token()}"},
        )
        try:
            with urllib.request.urlopen(request, timeout=60) as response:
                data = json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError:
            return None
        executions = data.get("executions") if isinstance(data, dict) else None
        if not isinstance(executions, list) or not executions:
            return None
        first = executions[0]
        if isinstance(first, dict):
            name = str(first.get("name") or "")
            return name if self._is_execution_name(name) else None
        return None

    @staticmethod
    def execution_terminal(execution: dict[str, Any]) -> bool:
        if execution.get("completionTime"):
            return True
        completion_status = str(execution.get("completionStatus") or "")
        if completion_status in {
            "EXECUTION_SUCCEEDED",
            "EXECUTION_FAILED",
            "EXECUTION_CANCELLED",
        }:
            return True
        for condition in execution.get("conditions") or []:
            if not isinstance(condition, dict):
                continue
            if condition.get("type") == "Completed":
                return True
        task_count = int(execution.get("taskCount") or 0)
        if task_count > 0:
            finished = (
                int(execution.get("succeededCount") or 0)
                + int(execution.get("failedCount") or 0)
                + int(execution.get("cancelledCount") or 0)
            )
            if finished >= task_count:
                return True
        return False

    @staticmethod
    def execution_outcome(execution: dict[str, Any]) -> ExecutionOutcome:
        if not CloudRunJobsDispatcher.execution_terminal(execution):
            return ExecutionOutcome.RUNNING
        completion_status = str(execution.get("completionStatus") or "")
        if completion_status == "EXECUTION_SUCCEEDED":
            return ExecutionOutcome.SUCCEEDED
        if completion_status == "EXECUTION_FAILED":
            return ExecutionOutcome.FAILED
        if completion_status == "EXECUTION_CANCELLED":
            return ExecutionOutcome.CANCELLED
        for condition in execution.get("conditions") or []:
            if not isinstance(condition, dict):
                continue
            if condition.get("type") != "Completed":
                continue
            state = str(condition.get("state") or "")
            if state == "CONDITION_SUCCEEDED":
                return ExecutionOutcome.SUCCEEDED
            if state == "CONDITION_FAILED":
                message = str(condition.get("message") or "").lower()
                if "cancel" in message:
                    return ExecutionOutcome.CANCELLED
                return ExecutionOutcome.FAILED
        if int(execution.get("failedCount") or 0) > 0:
            return ExecutionOutcome.FAILED
        if int(execution.get("cancelledCount") or 0) > 0:
            return ExecutionOutcome.CANCELLED
        if int(execution.get("succeededCount") or 0) > 0:
            return ExecutionOutcome.SUCCEEDED
        return ExecutionOutcome.UNKNOWN

    @staticmethod
    def execution_succeeded(execution: dict[str, Any]) -> bool:
        return CloudRunJobsDispatcher.execution_outcome(execution) == ExecutionOutcome.SUCCEEDED

    @staticmethod
    def execution_meta(execution: dict[str, Any]) -> dict[str, Any]:
        outcome = CloudRunJobsDispatcher.execution_outcome(execution)
        log_uri = execution.get("logUri") or execution.get("log_uri")
        return {
            "execution_name": execution.get("name"),
            "create_time": execution.get("createTime"),
            "completion_time": execution.get("completionTime"),
            "completion_status": execution.get("completionStatus"),
            "outcome": outcome.value,
            "log_uri": log_uri,
            "succeeded_count": execution.get("succeededCount"),
            "failed_count": execution.get("failedCount"),
            "cancelled_count": execution.get("cancelledCount"),
            "task_count": execution.get("taskCount"),
        }

    @staticmethod
    def execution_failure_detail(execution: dict[str, Any]) -> str:
        outcome = CloudRunJobsDispatcher.execution_outcome(execution)
        parts: list[str] = [f"outcome={outcome.value}"]
        for condition in execution.get("conditions") or []:
            if not isinstance(condition, dict):
                continue
            if condition.get("type") == "Completed" and condition.get("state") == "CONDITION_FAILED":
                message = condition.get("message")
                if message:
                    parts.append(str(message))
        if execution.get("error"):
            parts.append(str(execution["error"]))
        completion_status = execution.get("completionStatus")
        if completion_status and completion_status not in {"EXECUTION_SUCCEEDED"}:
            parts.append(f"completionStatus={completion_status}")
        log_uri = execution.get("logUri") or execution.get("log_uri")
        if log_uri:
            parts.append(f"log={log_uri}")
        name = execution.get("name")
        if name:
            parts.append(f"execution={name}")
        return "; ".join(parts) if parts else "Cloud Run job execution failed."

    def wait_for_execution(
        self,
        execution_name: str,
        *,
        timeout_seconds: float = 7200,
        poll_interval_seconds: float = 5.0,
        on_poll: Callable[[dict[str, Any], ExecutionOutcome], None] | None = None,
    ) -> dict[str, Any]:
        if self._is_operation_name(execution_name):
            pipeline_log(f"wait_for_execution resolving operation first: {execution_name}")
            operation = self.wait_for_operation(
                execution_name,
                timeout_seconds=min(timeout_seconds, self._operation_timeout_seconds()),
            )
            resolved = self._execution_name_from_operation(operation)
            if not resolved:
                raise RuntimeError(
                    f"Operation completed without execution name: {execution_name}"
                )
            execution_name = resolved
        pipeline_log(
            f"waiting for execution={execution_name} timeout={int(timeout_seconds)}s"
        )
        deadline = time.time() + timeout_seconds
        last_outcome = ExecutionOutcome.RUNNING
        while time.time() < deadline:
            execution = self.get_execution(execution_name)
            outcome = self.execution_outcome(execution)
            if outcome != last_outcome:
                pipeline_log(
                    f"execution status change execution={execution_name} outcome={outcome.value} "
                    f"completionStatus={execution.get('completionStatus')} "
                    f"succeeded={execution.get('succeededCount')} "
                    f"failed={execution.get('failedCount')}"
                )
                last_outcome = outcome
            if on_poll is not None:
                on_poll(execution, outcome)
            if self.execution_terminal(execution):
                pipeline_log(
                    f"execution terminal execution={execution_name} outcome={outcome.value}"
                )
                return execution
            time.sleep(poll_interval_seconds)
        raise TimeoutError(f"Timed out waiting for Cloud Run execution {execution_name}")

    def dispatch_with_meta(
        self,
        *,
        job_type: JobType,
        client_id: str,
        job_id: str,
        eval_llm_mode: str | None = None,
        eval_suite: str | None = None,
    ) -> DispatchResult:
        use_gcloud = os.getenv("CLOUD_RUN_JOBS_USE_GCLOUD", "").strip().lower() in {
            "1",
            "true",
            "yes",
            "on",
        }
        if use_gcloud:
            job_name = self.job_name(job_type)
            self._run_via_gcloud(job_type=job_type, client_id=client_id, job_id=job_id)
            latest = self.list_latest_execution(job_type)
            return DispatchResult(
                job_type=job_type,
                job_name=job_name,
                region=self._region,
                client_id=client_id,
                execution_name=latest or f"gcloud:{job_name}",
            )
        return self._run_via_api_with_meta(
            job_type=job_type,
            client_id=client_id,
            job_id=job_id,
            eval_llm_mode=eval_llm_mode,
            eval_suite=eval_suite,
        )

    def dispatch(
        self,
        *,
        job_type: JobType,
        client_id: str,
        job_id: str,
        eval_llm_mode: str | None = None,
        eval_suite: str | None = None,
    ) -> str:
        result = self.dispatch_with_meta(
            job_type=job_type,
            client_id=client_id,
            job_id=job_id,
            eval_llm_mode=eval_llm_mode,
            eval_suite=eval_suite,
        )
        if not result.execution_name:
            raise RuntimeError(f"Dispatch for {result.job_name} returned no execution name.")
        return result.execution_name

    def _run_via_gcloud(self, *, job_type: JobType, client_id: str, job_id: str) -> str:
        job_name = self.job_name(job_type)
        args = [
            "gcloud",
            "run",
            "jobs",
            "execute",
            job_name,
            f"--region={self._region}",
            f"--project={self._project}",
            "--quiet",
            f"--update-env-vars=JOB_TYPE={job_type.value},CLIENT_ID={client_id},JOB_ID={job_id}",
        ]
        subprocess.run(args, check=True)
        return f"gcloud:{job_name}"

    def _run_via_api_with_meta(
        self,
        *,
        job_type: JobType,
        client_id: str,
        job_id: str,
        eval_llm_mode: str | None = None,
        eval_suite: str | None = None,
    ) -> DispatchResult:
        job_name = self.job_name(job_type)
        url = (
            f"https://run.googleapis.com/v2/projects/{self._project}/locations/"
            f"{self._region}/jobs/{job_name}:run"
        )
        cli_step = _JOB_TYPE_CLI[job_type]
        container_args = ["job", cli_step, "--client-id", client_id]
        if job_type == JobType.EVAL:
            container_args.extend(["--suite", eval_suite or "full"])
            container_args.extend(["--llm-mode", eval_llm_mode or "live"])

        body: dict[str, Any] = {
            "overrides": {
                "containerOverrides": [
                    {
                        "args": container_args,
                        "env": [
                            {"name": "JOB_TYPE", "value": job_type.value},
                            {"name": "CLIENT_ID", "value": client_id},
                            {"name": "JOB_ID", "value": job_id},
                        ],
                    }
                ]
            }
        }
        pipeline_log(
            f"dispatch POST job={job_name} region={self._region} client={client_id} job_id={job_id}"
        )
        run_response = self._api_post(url, body)
        resolved = self.resolve_run_response(job_type=job_type, run_response=run_response)
        resolved.client_id = client_id
        if not resolved.execution_name:
            fallback = self.list_latest_execution(job_type)
            if fallback:
                pipeline_log(f"dispatch fallback latest execution={fallback}")
                resolved.execution_name = fallback
        if not resolved.execution_name:
            raise RuntimeError(f"Cloud Run job dispatch returned no execution name for {job_name}")
        logger.info(
            "Dispatched Cloud Run job=%s client=%s job_id=%s operation=%s execution=%s",
            job_name,
            client_id,
            job_id,
            resolved.operation_name,
            resolved.execution_name,
        )
        pipeline_log(
            f"dispatch complete job={job_name} operation={resolved.operation_name} "
            f"execution={resolved.execution_name}"
        )
        return resolved

    def dispatch_pipeline(self, *, client_id: str, pipeline_id: str) -> str:
        result = self.dispatch_pipeline_with_meta(client_id=client_id, pipeline_id=pipeline_id)
        if not result.execution_name:
            raise RuntimeError("Cloud Run pipeline dispatch returned no execution name.")
        return result.execution_name

    def dispatch_pipeline_with_meta(
        self, *, client_id: str, pipeline_id: str
    ) -> DispatchResult:
        use_gcloud = os.getenv("CLOUD_RUN_JOBS_USE_GCLOUD", "").strip().lower() in {
            "1",
            "true",
            "yes",
            "on",
        }
        if use_gcloud:
            job_name = self.job_name(JobType.PIPELINE)
            args = [
                "gcloud",
                "run",
                "jobs",
                "execute",
                job_name,
                f"--region={self._region}",
                f"--project={self._project}",
                "--quiet",
                (
                    "--args=job,pipeline,--client-id,"
                    f"{client_id},--pipeline-id,{pipeline_id}"
                ),
            ]
            subprocess.run(args, check=True)
            latest = self.list_latest_execution(JobType.PIPELINE)
            return DispatchResult(
                job_type=JobType.PIPELINE,
                job_name=job_name,
                region=self._region,
                client_id=client_id,
                execution_name=latest or f"gcloud:{job_name}",
            )
        return self._run_pipeline_via_api_with_meta(
            client_id=client_id,
            pipeline_id=pipeline_id,
        )

    def _run_pipeline_via_api_with_meta(
        self, *, client_id: str, pipeline_id: str
    ) -> DispatchResult:
        job_name = self.job_name(JobType.PIPELINE)
        url = (
            f"https://run.googleapis.com/v2/projects/{self._project}/locations/"
            f"{self._region}/jobs/{job_name}:run"
        )
        container_args = [
            "job",
            "pipeline",
            "--client-id",
            client_id,
            "--pipeline-id",
            pipeline_id,
        ]
        body: dict[str, Any] = {
            "overrides": {
                "containerOverrides": [
                    {
                        "args": container_args,
                        "env": [
                            {"name": "CLIENT_ID", "value": client_id},
                            {"name": "PIPELINE_ID", "value": pipeline_id},
                        ],
                    }
                ]
            }
        }
        pipeline_log(
            f"dispatch pipeline POST job={job_name} client={client_id} pipeline_id={pipeline_id}"
        )
        run_response = self._api_post(url, body)
        resolved = self.resolve_run_response(job_type=JobType.PIPELINE, run_response=run_response)
        resolved.client_id = client_id
        if not resolved.execution_name:
            fallback = self.list_latest_execution(JobType.PIPELINE)
            if fallback:
                resolved.execution_name = fallback
        if not resolved.execution_name:
            raise RuntimeError(
                f"Cloud Run pipeline dispatch returned no execution name for {job_name}"
            )
        logger.info(
            "Dispatched Cloud Run pipeline job=%s client=%s pipeline_id=%s execution=%s",
            job_name,
            client_id,
            pipeline_id,
            resolved.execution_name,
        )
        return resolved


def build_cloud_run_jobs_dispatcher() -> CloudRunJobsDispatcher | None:
    project = os.getenv("GOOGLE_CLOUD_PROJECT", "").strip()
    if not project:
        return None
    region = os.getenv("CLOUD_RUN_REGION", "europe-west1").strip()
    prefix = os.getenv("CLOUD_RUN_JOB_PREFIX", "chatbot").strip()
    return CloudRunJobsDispatcher(project=project, region=region, job_prefix=prefix)
