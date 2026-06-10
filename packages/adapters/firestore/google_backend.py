from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from packages.core.control_plane.models import WidgetKeyRecord
from packages.core.tenant.paths import safe_client_id


class GoogleFirestoreBackend:
    """Production Firestore backend mirroring InMemoryFirestoreBackend interface."""

    def __init__(self, client: Any, *, database: str | None = None) -> None:
        self._client = client
        self._database = database

    def _clients(self):
        return self._client.collection("clients")

    def upsert_client(self, client_id: str, data: dict[str, Any]) -> None:
        cid = safe_client_id(client_id)
        self._clients().document(cid).set(data, merge=True)

    def get_client(self, client_id: str) -> dict[str, Any] | None:
        cid = safe_client_id(client_id)
        snap = self._clients().document(cid).get()
        if not snap.exists:
            return None
        data = snap.to_dict() or {}
        data.setdefault("client_id", cid)
        return data

    def list_client_ids(self) -> list[str]:
        return sorted(doc.id for doc in self._clients().stream())

    def upsert_widget_key(self, client_id: str, key_id: str, data: dict[str, Any]) -> None:
        cid = safe_client_id(client_id)
        self._clients().document(cid).collection("widget_keys").document(key_id).set(data, merge=True)

    def get_widget_key(self, client_id: str, key_id: str) -> dict[str, Any] | None:
        cid = safe_client_id(client_id)
        snap = self._clients().document(cid).collection("widget_keys").document(key_id).get()
        if not snap.exists:
            return None
        return snap.to_dict()

    def list_widget_keys(self, client_id: str) -> list[dict[str, Any]]:
        cid = safe_client_id(client_id)
        return [snap.to_dict() or {} for snap in self._clients().document(cid).collection("widget_keys").stream()]

    def query_widget_keys_by_prefix(self, prefix: str, *, status: str = "active") -> list[WidgetKeyRecord]:
        query = (
            self._client.collection_group("widget_keys")
            .where("key_prefix", "==", prefix)
            .where("status", "==", status)
        )
        out: list[WidgetKeyRecord] = []
        for snap in query.stream():
            data = snap.to_dict() or {}
            client_id = snap.reference.parent.parent.id
            out.append(WidgetKeyRecord.from_dict(data, client_id=client_id))
        return out

    def upsert_config_meta(self, client_id: str, config_key: str, data: dict[str, Any]) -> None:
        cid = safe_client_id(client_id)
        self._clients().document(cid).collection("config_meta").document(config_key).set(data, merge=True)

    def get_config_meta(self, client_id: str, config_key: str) -> dict[str, Any] | None:
        cid = safe_client_id(client_id)
        snap = self._clients().document(cid).collection("config_meta").document(config_key).get()
        if not snap.exists:
            return None
        return snap.to_dict()

    def list_config_meta(self, client_id: str) -> list[dict[str, Any]]:
        cid = safe_client_id(client_id)
        return [
            snap.to_dict() or {}
            for snap in self._clients().document(cid).collection("config_meta").stream()
        ]

    def upsert_job(self, client_id: str, job_id: str, data: dict[str, Any]) -> None:
        cid = safe_client_id(client_id)
        expires_at = data.get("expires_at")
        doc_ref = self._clients().document(cid).collection("jobs").document(job_id)
        doc_ref.set(data, merge=True)
        if expires_at is None:
            created = data.get("created_at")
            if created:
                try:
                    created_dt = datetime.fromisoformat(str(created))
                    if created_dt.tzinfo is None:
                        created_dt = created_dt.replace(tzinfo=timezone.utc)
                    from datetime import timedelta

                    doc_ref.update({"expires_at": (created_dt + timedelta(days=90)).isoformat()})
                except ValueError:
                    pass

    def get_job(self, client_id: str, job_id: str) -> dict[str, Any] | None:
        cid = safe_client_id(client_id)
        snap = self._clients().document(cid).collection("jobs").document(job_id).get()
        if not snap.exists:
            return None
        return snap.to_dict()

    def list_jobs(self, client_id: str, *, limit: int = 50) -> list[dict[str, Any]]:
        cid = safe_client_id(client_id)
        query = (
            self._clients()
            .document(cid)
            .collection("jobs")
            .order_by("created_at", direction="DESCENDING")
            .limit(limit)
        )
        return [snap.to_dict() or {} for snap in query.stream()]

    def upsert_pipeline(self, client_id: str, pipeline_id: str, data: dict[str, Any]) -> None:
        cid = safe_client_id(client_id)
        doc_ref = self._clients().document(cid).collection("pipelines").document(pipeline_id)
        doc_ref.set(data, merge=True)
        expires_at = data.get("expires_at")
        if expires_at is None:
            created = data.get("created_at")
            if created:
                try:
                    created_dt = datetime.fromisoformat(str(created))
                    if created_dt.tzinfo is None:
                        created_dt = created_dt.replace(tzinfo=timezone.utc)
                    from datetime import timedelta

                    doc_ref.update({"expires_at": (created_dt + timedelta(days=90)).isoformat()})
                except ValueError:
                    pass

    def get_pipeline(self, client_id: str, pipeline_id: str) -> dict[str, Any] | None:
        cid = safe_client_id(client_id)
        snap = self._clients().document(cid).collection("pipelines").document(pipeline_id).get()
        if not snap.exists:
            return None
        return snap.to_dict()

    def list_pipelines(self, client_id: str, *, limit: int = 20) -> list[dict[str, Any]]:
        cid = safe_client_id(client_id)
        query = (
            self._clients()
            .document(cid)
            .collection("pipelines")
            .order_by("created_at", direction="DESCENDING")
            .limit(limit)
        )
        return [snap.to_dict() or {} for snap in query.stream()]


def build_google_firestore_client() -> Any:
    from google.cloud import firestore

    database = (__import__("os").getenv("FIRESTORE_DATABASE") or "(default)").strip()
    project = (__import__("os").getenv("GOOGLE_CLOUD_PROJECT") or "").strip() or None
    if database and database != "(default)":
        return firestore.Client(project=project, database=database)
    return firestore.Client(project=project)
