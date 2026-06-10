from __future__ import annotations

import json
import logging
import os
import subprocess
import time
import urllib.error
import urllib.request
from typing import Any

import google.auth
from google.auth.transport.requests import Request as GoogleAuthRequest

from packages.core.jobs.models import JobType

logger = logging.getLogger(__name__)

_JOB_TYPE_CLI: dict[JobType, str] = {
    JobType.DRIVE_SYNC: "drive-sync",
    JobType.INGEST: "ingest",
    JobType.EVAL: "eval",
    JobType.DEPLOY: "deploy",
}


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

    def job_name(self, job_type: JobType) -> str:
        return f"{self._job_prefix}-{job_type.value.replace('_', '-')}"

    def _auth_token(self) -> str:
        credentials, _ = google.auth.default(
            scopes=["https://www.googleapis.com/auth/cloud-platform"]
        )
        credentials.refresh(GoogleAuthRequest())
        return credentials.token

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

    def _run_via_api(
        self,
        *,
        job_type: JobType,
        client_id: str,
        job_id: str,
        eval_llm_mode: str | None = None,
        eval_suite: str | None = None,
    ) -> str:
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
            raise RuntimeError(
                f"Cloud Run job dispatch failed for {job_name}: HTTP {exc.code} {detail}"
            ) from exc
        execution_name = str(data.get("name") or "")
        if not execution_name:
            raise RuntimeError(f"Cloud Run job dispatch returned no execution name for {job_name}")
        logger.info(
            "Dispatched Cloud Run job=%s client=%s job_id=%s execution=%s",
            job_name,
            client_id,
            job_id,
            execution_name,
        )
        return execution_name

    def get_execution(self, execution_name: str) -> dict[str, Any]:
        url = f"https://run.googleapis.com/v2/{execution_name.lstrip('/')}"
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
                f"Cloud Run execution lookup failed for {execution_name}: HTTP {exc.code} {detail}"
            ) from exc
        return data if isinstance(data, dict) else {}

    @staticmethod
    def execution_terminal(execution: dict[str, Any]) -> bool:
        if execution.get("completionTime"):
            return True
        for condition in execution.get("conditions") or []:
            if not isinstance(condition, dict):
                continue
            if condition.get("type") == "Completed":
                return True
        return False

    @staticmethod
    def execution_succeeded(execution: dict[str, Any]) -> bool:
        for condition in execution.get("conditions") or []:
            if not isinstance(condition, dict):
                continue
            if condition.get("type") == "Completed":
                return condition.get("state") == "CONDITION_SUCCEEDED"
        return bool(execution.get("completionTime")) and not execution.get("error")

    def wait_for_execution(
        self,
        execution_name: str,
        *,
        timeout_seconds: float = 7200,
        poll_interval_seconds: float = 5.0,
    ) -> dict[str, Any]:
        deadline = time.time() + timeout_seconds
        while time.time() < deadline:
            execution = self.get_execution(execution_name)
            if self.execution_terminal(execution):
                return execution
            time.sleep(poll_interval_seconds)
        raise TimeoutError(f"Timed out waiting for Cloud Run execution {execution_name}")

    def dispatch(
        self,
        *,
        job_type: JobType,
        client_id: str,
        job_id: str,
        eval_llm_mode: str | None = None,
        eval_suite: str | None = None,
    ) -> str:
        use_gcloud = os.getenv("CLOUD_RUN_JOBS_USE_GCLOUD", "").strip().lower() in {
            "1",
            "true",
            "yes",
            "on",
        }
        if use_gcloud:
            return self._run_via_gcloud(job_type=job_type, client_id=client_id, job_id=job_id)
        return self._run_via_api(
            job_type=job_type,
            client_id=client_id,
            job_id=job_id,
            eval_llm_mode=eval_llm_mode,
            eval_suite=eval_suite,
        )


def build_cloud_run_jobs_dispatcher() -> CloudRunJobsDispatcher | None:
    project = os.getenv("GOOGLE_CLOUD_PROJECT", "").strip()
    if not project:
        return None
    region = os.getenv("CLOUD_RUN_REGION", "europe-west1").strip()
    prefix = os.getenv("CLOUD_RUN_JOB_PREFIX", "chatbot").strip()
    return CloudRunJobsDispatcher(project=project, region=region, job_prefix=prefix)
