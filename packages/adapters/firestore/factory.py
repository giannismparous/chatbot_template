from __future__ import annotations

from typing import Any

from packages.adapters.firestore.google_backend import GoogleFirestoreBackend, build_google_firestore_client
from packages.adapters.firestore.in_memory_stores import (
    InMemoryClientRegistryStore,
    InMemoryConfigMetaStore,
    InMemoryJobStore,
)
from packages.core.control_plane.widget_key_hmac import widget_key_hash_secret
from packages.core.ports.client_registry import ClientRegistryStore
from packages.core.ports.config_meta_store import ConfigMetaStore
from packages.core.ports.job_store import JobStore


def build_firestore_stores(
    *,
    backend: Any | None = None,
    hash_secret: bytes | None = None,
) -> tuple[ClientRegistryStore, ConfigMetaStore, JobStore]:
    secret = hash_secret if hash_secret is not None else widget_key_hash_secret()
    if backend is None:
        client = build_google_firestore_client()
        backend = GoogleFirestoreBackend(client)
    registry = InMemoryClientRegistryStore(backend, hash_secret=secret)
    config_meta = InMemoryConfigMetaStore(backend)
    jobs = InMemoryJobStore(backend)
    return registry, config_meta, jobs
