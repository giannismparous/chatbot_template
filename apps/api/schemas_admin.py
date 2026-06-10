from __future__ import annotations

from typing import Any, Literal, Optional

from pydantic import BaseModel, Field


class WidgetKeySummaryDTO(BaseModel):
    key_id: Optional[str] = None
    key_prefix: Optional[str] = None
    allowed_origins: list[str] = Field(default_factory=list)
    status: Optional[str] = None
    created_at: Optional[str] = None
    revoked_at: Optional[str] = None


class WidgetKeyRotateRequest(BaseModel):
    allowed_origins: list[str] = Field(default_factory=list)
    revoke_key_id: Optional[str] = None


class WidgetKeyRotateResponse(BaseModel):
    client_id: str
    key_id: str
    widget_key_prefix: str
    allowed_origins: list[str] = Field(default_factory=list)
    widget_key: str
    revoked_key_id: Optional[str] = None


class ClientCreateRequest(BaseModel):
    client_id: str
    display_name: Optional[str] = None
    domain_pack: str = "generic"
    allowed_origins: list[str] = Field(default_factory=list)
    reveal_widget_key: bool = False


class ClientCreateResponse(BaseModel):
    client_id: str
    display_name: str
    domain_pack: str
    widget_key_prefix: str
    allowed_origins: list[str] = Field(default_factory=list)
    widget_key: Optional[str] = None


class ClientSummaryDTO(BaseModel):
    client_id: str
    display_name: Optional[str] = None
    widget_keys: list[WidgetKeySummaryDTO] = Field(default_factory=list)
    has_config: bool = False


class ConfigGetResponse(BaseModel):
    key: str
    data: dict[str, Any] = Field(default_factory=dict)


class ConfigPutRequest(BaseModel):
    data: dict[str, Any] = Field(default_factory=dict)


class ConfigPutResponse(BaseModel):
    key: str
    status: str = "ok"


class UploadCitationDTO(BaseModel):
    citation_url: Optional[str] = None
    title: Optional[str] = None
    status: Literal[
        "internal_only",
        "public_configured",
        "blocked_by_whitelist",
        "invalid_url",
    ] = "internal_only"
    requires_reingest: bool = False


class UploadCitationPutRequest(BaseModel):
    citation_url: str
    title: Optional[str] = None
    source_visibility: Literal["public", "internal"] = "public"


class UploadEntryDTO(BaseModel):
    path: str
    size_bytes: int
    citation: Optional[UploadCitationDTO] = None


class UploadListDTO(BaseModel):
    files: list[UploadEntryDTO] = Field(default_factory=list)


class UploadResultDTO(BaseModel):
    path: str
    size_bytes: int
    status: str = "ok"


class JobAcceptedDTO(BaseModel):
    job_id: str
    job_type: str
    status: str


class JobStatusDTO(BaseModel):
    job_id: str
    client_id: str
    job_type: str
    status: str
    created_at: str
    updated_at: str
    result: dict[str, Any] = Field(default_factory=dict)
    error: Optional[str] = None


class EvalJobRequest(BaseModel):
    suite: str = "full"
    llm_mode: str = "replay"


class DeployRequest(BaseModel):
    """Deploy pending index — no skip-gate or bypass parameters."""

    pass


class DeployResponse(BaseModel):
    status: str
    activated_version: str
    eval_run_id: Optional[str] = None


class DeployConflictResponse(BaseModel):
    reason: str
    detail: str


class RollbackResponse(BaseModel):
    status: str = "ok"
    active_version: str


class IndexStatusDTO(BaseModel):
    active: Optional[str] = None
    pending: Optional[str] = None
    previous: Optional[str] = None


class EvalSummaryDTO(BaseModel):
    run_id: Optional[str] = None
    status: Optional[str] = None
    evaluated_index_version: Optional[str] = None
    evaluated_at: Optional[str] = None
    deploy_eligible: bool = False
    categories: dict[str, Any] = Field(default_factory=dict)
    failure_reasons: list[str] = Field(default_factory=list)
    failed_cases: list[dict[str, Any]] = Field(default_factory=list)


class MetricsSummaryDTO(BaseModel):
    client_id: str
    updated_at: str
    total_chats: int = 0
    no_context: int = 0
    crisis: int = 0
    input_blocked: int = 0
    provider_fallback: int = 0
    avg_latency_ms: Optional[float] = None
    confidence_buckets: dict[str, int] = Field(default_factory=dict)


WebSourceStatusDTO = Literal[
    "configured",
    "fetched",
    "failed",
    "failed_render",
    "failed_extraction",
    "fetched_low_content",
    "blocked_by_whitelist",
    "disabled",
    "stale",
]


class WebSourceDTO(BaseModel):
    id: str
    url: str
    title: Optional[str] = None
    enabled: bool = True
    max_depth: int = 0
    max_pages: int = 1
    render_mode: Literal["static", "playwright"] = "static"
    wait_until: Literal["networkidle", "domcontentloaded", "load"] = "networkidle"
    wait_selector: Optional[str] = None
    status: WebSourceStatusDTO = "configured"
    last_crawled_at: Optional[str] = None
    pages_fetched: int = 0
    pages_failed: int = 0
    last_error: Optional[str] = None
    admin_message: Optional[str] = None


class WebSourcesListDTO(BaseModel):
    defaults: dict[str, Any] = Field(default_factory=dict)
    sources: list[WebSourceDTO] = Field(default_factory=list)


class WebSourceCreateRequest(BaseModel):
    url: str
    title: Optional[str] = None
    enabled: bool = True
    max_depth: int = 0
    max_pages: int = 1
    id: Optional[str] = None
    render_mode: Literal["static", "playwright"] = "static"
    wait_until: Literal["networkidle", "domcontentloaded", "load"] = "networkidle"
    wait_selector: Optional[str] = None


class CrawlJobRequest(BaseModel):
    source_ids: Optional[list[str]] = None


DriveSourceStatusDTO = Literal[
    "configured",
    "synced",
    "synced_with_warnings",
    "failed_auth",
    "failed_extraction",
    "disabled",
    "stale",
]


class DriveSourceDTO(BaseModel):
    id: str
    folder_id: str
    title: Optional[str] = None
    enabled: bool = True
    recursive: bool = True
    max_files: int = 200
    status: DriveSourceStatusDTO = "configured"
    last_synced_at: Optional[str] = None
    files_discovered: int = 0
    files_synced: int = 0
    files_failed: int = 0
    files_skipped: int = 0
    files_skipped_unchanged: int = 0
    sync_summary: Optional[str] = None
    failure_breakdown: dict[str, int] = Field(default_factory=dict)
    last_error: Optional[str] = None
    admin_message: Optional[str] = None


class DriveSourcesListDTO(BaseModel):
    defaults: dict[str, Any] = Field(default_factory=dict)
    sources: list[DriveSourceDTO] = Field(default_factory=list)
    credentials_configured: bool = False
    service_account_email: Optional[str] = None
    credentials_error: Optional[str] = None


class DriveSourceCreateRequest(BaseModel):
    folder_id: str
    title: Optional[str] = None
    enabled: bool = True
    recursive: bool = True
    max_files: int = 200
    id: Optional[str] = None


class DriveSyncJobRequest(BaseModel):
    source_ids: Optional[list[str]] = None


class PipelineRunRequest(BaseModel):
    preset: Optional[str] = None
    steps: Optional[list[str]] = None
    eval_llm_mode: str = "live"
    eval_suite: str = "full"
    force_empty_deploy: bool = False
    drive_source_ids: Optional[list[str]] = None


class PipelineStepResultDTO(BaseModel):
    step: str
    status: str
    job_id: Optional[str] = None
    cloud_run_execution: Optional[str] = None
    result: dict[str, Any] = Field(default_factory=dict)
    error: Optional[str] = None
    execution_meta: dict[str, Any] = Field(default_factory=dict)


class PipelineMarkFailedRequest(BaseModel):
    reason: str = "Manually marked failed by admin."


class PipelineRunAcceptedDTO(BaseModel):
    pipeline_id: str
    client_id: str
    status: str
    preset: Optional[str] = None
    steps: list[str] = Field(default_factory=list)
    runner_execution: Optional[str] = None


class PipelineRunDTO(BaseModel):
    pipeline_id: str
    client_id: str
    status: str
    preset: Optional[str] = None
    steps: list[str] = Field(default_factory=list)
    current_step: Optional[str] = None
    created_at: str
    updated_at: str
    started_at: Optional[str] = None
    finished_at: Optional[str] = None
    active_version_before: Optional[str] = None
    pending_version_after_ingest: Optional[str] = None
    active_version_after_deploy: Optional[str] = None
    step_results: list[PipelineStepResultDTO] = Field(default_factory=list)
    ingest_summary: dict[str, Any] = Field(default_factory=dict)
    eval_summary: dict[str, Any] = Field(default_factory=dict)
    index_manifest: dict[str, Any] = Field(default_factory=dict)
    force_empty_deploy: bool = False
    eval_llm_mode: str = "live"
    eval_suite: str = "full"
    runner_execution: Optional[str] = None
    error: Optional[str] = None
    runtime_refresh_note: Optional[str] = None
