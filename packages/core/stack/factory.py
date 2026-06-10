from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from packages.adapters.auth.firestore_widget_auth import FirestoreWidgetAuthProvider
from packages.adapters.auth.local_dev_auth import LocalDevAuthProvider
from packages.adapters.auth.local_token_admin_auth import LocalTokenAdminAuthProvider
from packages.adapters.config.yaml_config_store import build_yaml_config_store
from packages.adapters.firestore.factory import build_firestore_stores
from packages.adapters.firestore.in_memory_backend import InMemoryFirestoreBackend
from packages.adapters.metrics.local_sqlite_metrics_store import LocalSqliteMetricsStore
from packages.adapters.registry.yaml_client_registry import YamlClientRegistryStore
from packages.adapters.sessions.local_sqlite_session_store import LocalSqliteSessionStore
from packages.adapters.storage.gcs_file_store import GcsFileStore
from packages.adapters.storage.local_file_store import LocalFileStore
from packages.adapters.traces.local_sqlite_trace_store import LocalSqliteTraceStore
from packages.adapters.traces.sqlite_db import traces_db_path
from packages.config.loaders import load_yaml
from packages.core.control_plane.flags import firestore_control_plane_enabled, gcs_registry_fallback_enabled
from packages.core.control_plane.widget_key_hmac import widget_key_hash_secret
from packages.core.ports.admin_auth import AdminAuthProvider
from packages.core.ports.auth import AuthProvider
from packages.core.ports.client_registry import ClientRegistryStore
from packages.core.ports.config_meta_store import ConfigMetaStore
from packages.core.ports.config_store import ConfigStore
from packages.core.ports.file_store import FileStore
from packages.adapters.pipeline.local_pipeline_store import LocalPipelineStore
from packages.core.ports.job_store import JobStore
from packages.core.ports.pipeline_store import PipelineStore
from packages.core.ports.metrics_store import MetricsStore
from packages.core.ports.session_store import SessionStore
from packages.core.ports.trace_store import TraceStore
from packages.core.storage.tenant_cache_hydrator import hydrate_startup_tenant_configs
from packages.core.storage.tenant_storage import TenantStorage


@dataclass(frozen=True)
class Stack:
    profile: str
    config: dict[str, Any]
    config_store: ConfigStore
    file_store: FileStore
    tenant_storage: TenantStorage
    registry_store: ClientRegistryStore
    config_meta_store: ConfigMetaStore | None
    job_store: JobStore | None
    auth_provider: AuthProvider
    admin_auth_provider: AdminAuthProvider
    trace_store: TraceStore
    metrics_store: MetricsStore
    session_store: SessionStore
    job_runner: Any
    pipeline_store: PipelineStore


def project_root() -> Path:
    return Path(__file__).resolve().parents[3]


def _load_stack_yaml(profile: str) -> dict[str, Any]:
    root = project_root()
    path = root / "config" / "stacks" / f"{profile}.yaml"
    if not path.is_file():
        raise FileNotFoundError(f"Stack profile config not found: {path}")
    data = load_yaml(str(path))
    if not isinstance(data, dict):
        raise ValueError(f"Invalid stack config: {path}")
    if data.get("status") == "documented_not_implemented":
        raise RuntimeError(
            f"Stack profile {profile!r} is documented only and not implemented."
        )
    return data


def _default_gcs_bucket(project_id: str) -> str:
    override = os.getenv("GCS_BUCKET", "").strip()
    if override:
        return override
    if not project_id:
        raise RuntimeError("GCS_BUCKET or GOOGLE_CLOUD_PROJECT is required for firebase profile.")
    return f"simasia-chatbot-prod-{project_id}"


def build_file_store(profile: str, stack_yaml: dict[str, Any], project_root_path: Path) -> FileStore:
    store_kind = str(stack_yaml.get("file_store") or "local_files")
    if profile == "local" or store_kind in {"local_files", "local"}:
        paths = stack_yaml.get("paths") or {}
        clients_root = Path(os.getenv("CLIENTS_ROOT", paths.get("clients_root", "data/clients")))
        if not clients_root.is_absolute():
            clients_root = project_root_path / clients_root
        return LocalFileStore(clients_root)

    if store_kind == "gcs":
        project_id = os.getenv("GOOGLE_CLOUD_PROJECT", "").strip()
        bucket = _default_gcs_bucket(project_id)
        cache_root = Path(os.getenv("TENANT_CACHE_ROOT", "/tmp/simasia-tenant-cache"))
        return GcsFileStore(bucket_name=bucket, cache_root=cache_root)

    raise ValueError(f"Unsupported file_store for profile {profile!r}: {store_kind}")


def validate_stack_security(profile: str) -> None:
    if profile != "firebase":
        return
    admin_token = os.getenv("ADMIN_API_TOKEN", "").strip()
    if not admin_token:
        raise RuntimeError(
            "STACK_PROFILE=firebase requires ADMIN_API_TOKEN. "
            "Admin endpoints must not run without credentials in production profiles."
        )
    if not os.getenv("GOOGLE_CLOUD_PROJECT", "").strip():
        raise RuntimeError("STACK_PROFILE=firebase requires GOOGLE_CLOUD_PROJECT.")
    _default_gcs_bucket(os.getenv("GOOGLE_CLOUD_PROJECT", "").strip())
    insecure_client = os.getenv("ALLOW_INSECURE_CLIENT_ID", "false").strip().lower()
    if insecure_client in {"1", "true", "yes", "on"}:
        raise RuntimeError("ALLOW_INSECURE_CLIENT_ID must be false when STACK_PROFILE=firebase.")
    insecure_admin = os.getenv("ALLOW_INSECURE_ADMIN", "false").strip().lower()
    if insecure_admin in {"1", "true", "yes", "on"}:
        raise RuntimeError("ALLOW_INSECURE_ADMIN must be false when STACK_PROFILE=firebase.")
    if firestore_control_plane_enabled() and not gcs_registry_fallback_enabled():
        if not os.getenv("WIDGET_KEY_HASH_SECRET", "").strip():
            raise RuntimeError(
                "STACK_PROFILE=firebase with FIRESTORE_CONTROL_PLANE requires WIDGET_KEY_HASH_SECRET."
            )


def build_registry_and_jobs(
    profile: str,
    stack_yaml: dict[str, Any],
    project_root_path: Path,
    tenant_storage: TenantStorage,
) -> tuple[ClientRegistryStore, ConfigMetaStore | None, JobStore | None, AuthProvider]:
    paths = stack_yaml.get("paths") or {}
    clients_root = tenant_storage.clients_root()
    registry_path = Path(
        os.getenv(
            "CLIENT_REGISTRY_PATH",
            paths.get("registry", "packages/config/clients/registry.yaml"),
        )
    )
    if not registry_path.is_absolute():
        registry_path = project_root_path / registry_path

    if profile == "local" or (
        profile == "firebase" and gcs_registry_fallback_enabled()
    ):
        yaml_store = YamlClientRegistryStore(clients_root=clients_root, registry_path=registry_path)
        return yaml_store, None, None, LocalDevAuthProvider(build_yaml_config_store(
            project_root_path, stack_yaml, file_store=tenant_storage.file_store, profile=profile
        ))

    if profile == "firebase" and firestore_control_plane_enabled():
        hash_secret = widget_key_hash_secret()
        registry_store, config_meta_store, job_store = build_firestore_stores(hash_secret=hash_secret)
        auth_provider = FirestoreWidgetAuthProvider(registry_store, hash_secret=hash_secret)
        return registry_store, config_meta_store, job_store, auth_provider

    yaml_store = YamlClientRegistryStore(clients_root=clients_root, registry_path=registry_path)
    return yaml_store, None, None, LocalDevAuthProvider(
        build_yaml_config_store(project_root_path, stack_yaml, file_store=tenant_storage.file_store, profile=profile)
    )


def build_job_runner(
    profile: str,
    tenant_storage: TenantStorage,
    job_store: JobStore | None,
) -> Any:
    from packages.core.jobs.cloud_run_firestore_runner import CloudRunFirestoreJobRunner
    from packages.core.jobs.cloud_run_runner import CloudRunJobRunner
    from packages.core.jobs.firestore_runner import FirestoreJobRunner
    from packages.core.jobs.local_runner import LocalJobRunner

    if profile == "firebase" and firestore_control_plane_enabled() and job_store is not None:
        disabled = os.getenv("CLOUD_RUN_JOBS_DISABLED", "").strip().lower() in {
            "1",
            "true",
            "yes",
            "on",
        }
        if disabled:
            return FirestoreJobRunner(job_store=job_store)
        return CloudRunFirestoreJobRunner(job_store=job_store)

    if profile == "firebase" and os.getenv("CLOUD_RUN_JOBS_DISABLED", "").strip().lower() not in {
        "1",
        "true",
        "yes",
        "on",
    }:
        return CloudRunJobRunner(tenant_storage=tenant_storage)

    return LocalJobRunner(tenant_storage=tenant_storage)


def build_pipeline_store(
    profile: str,
    tenant_storage: TenantStorage,
    job_store: JobStore | None,
) -> PipelineStore:
    from packages.adapters.firestore.in_memory_stores import FirestorePipelineStore

    if profile == "firebase" and firestore_control_plane_enabled() and job_store is not None:
        backend = getattr(job_store, "_backend", None)
        if backend is not None:
            return FirestorePipelineStore(backend)
    return LocalPipelineStore(tenant_storage=tenant_storage)


def build_stack(profile: str | None = None) -> Stack:
    selected = (profile or os.getenv("STACK_PROFILE", "local")).strip() or "local"
    if selected == "enterprise":
        raise RuntimeError("STACK_PROFILE=enterprise is not implemented.")

    stack_yaml = _load_stack_yaml(selected)
    if selected not in {"local", "firebase"}:
        raise ValueError(f"Unsupported STACK_PROFILE: {selected}")

    validate_stack_security(selected)

    root = project_root()
    file_store = build_file_store(selected, stack_yaml, root)
    tenant_storage = TenantStorage.from_file_store(file_store, profile=selected)
    config_store = build_yaml_config_store(root, stack_yaml, file_store=file_store, profile=selected)
    registry_store, config_meta_store, job_store, auth_provider = build_registry_and_jobs(
        selected, stack_yaml, root, tenant_storage
    )
    admin_auth_provider = LocalTokenAdminAuthProvider()
    db_path = traces_db_path()
    trace_store = LocalSqliteTraceStore(db_path)
    metrics_store = LocalSqliteMetricsStore(db_path)
    session_store = LocalSqliteSessionStore(db_path)
    job_runner = build_job_runner(selected, tenant_storage, job_store)
    pipeline_store = build_pipeline_store(selected, tenant_storage, job_store)

    if selected == "firebase" and isinstance(file_store, GcsFileStore):
        default_client = os.getenv("DEFAULT_CLIENT_ID", "default").strip() or "default"
        hydrate_startup_tenant_configs(
            file_store=file_store,
            config_meta_store=config_meta_store,
            client_ids=[default_client],
        )

    return Stack(
        profile=selected,
        config=stack_yaml,
        config_store=config_store,
        file_store=file_store,
        tenant_storage=tenant_storage,
        registry_store=registry_store,
        config_meta_store=config_meta_store,
        job_store=job_store,
        auth_provider=auth_provider,
        admin_auth_provider=admin_auth_provider,
        trace_store=trace_store,
        metrics_store=metrics_store,
        session_store=session_store,
        job_runner=job_runner,
        pipeline_store=pipeline_store,
    )
