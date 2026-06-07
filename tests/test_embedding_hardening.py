from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Callable, Sequence

import pytest

from apps.worker.jobs.activate_index import activate_index
from apps.worker.jobs.rollback_index import rollback_index
from packages.adapters.embedding.gemini_embedding_adapter import GeminiEmbeddingAdapter
from packages.adapters.embedding.key_pool import (
    EmbeddingKeyPool,
    EmbeddingQuotaError,
    EmbeddingRateLimitError,
)
from packages.core.config.loader import TenantConfigLoader
from packages.core.ingestion.embeddings import validate_vector, EmbeddingValidationError
from packages.core.ingestion.paths import (
    ingest_report_path,
    knowledge_index_path,
    source_manifest_path,
    vector_index_path,
)
from packages.core.ingestion.pipeline import ingest_client_uploads
from packages.core.ports.embedding_provider import EmbeddingProvider

ROOT = Path(__file__).resolve().parents[1]
PACKS = ROOT / "packages" / "domain_packs"


class MockEmbeddingProvider(EmbeddingProvider):
    def __init__(self, *, dim: int = 4) -> None:
        self.dim = dim
        self.calls = 0
        self.seen_texts: list[str] = []
        self._handler: Callable[[Sequence[str]], list[list[float]]] | None = None

    @property
    def expected_dims(self) -> int | None:
        return self.dim

    def set_handler(self, handler: Callable[[Sequence[str]], list[list[float]]]) -> None:
        self._handler = handler

    def embed_texts(self, texts: Sequence[str], *, model: str) -> list[list[float]]:
        self.calls += 1
        self.seen_texts.extend(texts)
        if self._handler:
            return self._handler(texts)
        return [[0.1, 0.2, 0.3, 0.4] for _ in texts]


def _loader(clients_root: Path) -> TenantConfigLoader:
    return TenantConfigLoader(clients_root=clients_root, domain_packs_root=PACKS)


def _write_client(
    clients_root: Path,
    client_id: str,
    *,
    ingestion_yaml: str | None = None,
) -> None:
    config_dir = clients_root / client_id / "config"
    config_dir.mkdir(parents=True, exist_ok=True)
    (config_dir / "client.yaml").write_text(
        f"client_id: {client_id}\ndisplay_name: {client_id}\ndomain_pack: generic\n",
        encoding="utf-8",
    )
    if ingestion_yaml is not None:
        (config_dir / "ingestion.yaml").write_text(ingestion_yaml, encoding="utf-8")
    (clients_root / client_id / "uploads").mkdir(parents=True, exist_ok=True)
    (clients_root / client_id / "indexes" / "versions").mkdir(parents=True, exist_ok=True)


def test_embed_disabled_ingests_without_vector_index(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    clients_root = tmp_path / "clients"
    _write_client(clients_root, "tenant_a")
    (clients_root / "tenant_a" / "uploads" / "notes.txt").write_text("sparse only content", encoding="utf-8")

    result = ingest_client_uploads(
        clients_root=clients_root,
        client_id="tenant_a",
        config_loader=_loader(clients_root),
        version_id="sparse-v1",
    )

    assert result.embed_enabled is False
    assert result.vector_count == 0
    assert not vector_index_path(clients_root, "tenant_a", "sparse-v1").exists()
    chunks = json.loads(knowledge_index_path(clients_root, "tenant_a", "sparse-v1").read_text())["chunks"]
    assert chunks[0]["embedding_status"] == "not_embedded"


def test_embed_enabled_writes_vector_index(tmp_path: Path) -> None:
    clients_root = tmp_path / "clients"
    _write_client(
        clients_root,
        "tenant_a",
        ingestion_yaml="embed_enabled: true\nembed_batch_size: 8\n",
    )
    (clients_root / "tenant_a" / "uploads" / "notes.txt").write_text(
        "dense index unique phrase embed001",
        encoding="utf-8",
    )
    provider = MockEmbeddingProvider(dim=4)

    result = ingest_client_uploads(
        clients_root=clients_root,
        client_id="tenant_a",
        config_loader=_loader(clients_root),
        version_id="dense-v1",
        embedding_provider=provider,
    )

    assert result.embed_enabled is True
    assert result.vector_count == 1
    vector_payload = json.loads(vector_index_path(clients_root, "tenant_a", "dense-v1").read_text())
    assert vector_payload["embedding_dims"] == 4
    assert vector_payload["vectors"][0]["embedding"] == [0.1, 0.2, 0.3, 0.4]
    chunks = json.loads(knowledge_index_path(clients_root, "tenant_a", "dense-v1").read_text())["chunks"]
    assert chunks[0]["embedding_status"] == "embedded"
    assert "embedding" not in chunks[0]


def test_zero_vector_marks_chunk_failed_and_excludes_from_vector_index(tmp_path: Path) -> None:
    clients_root = tmp_path / "clients"
    _write_client(clients_root, "tenant_a", ingestion_yaml="embed_enabled: true\n")
    (clients_root / "tenant_a" / "uploads" / "bad.txt").write_text("zero vector content", encoding="utf-8")
    provider = MockEmbeddingProvider(dim=4)
    provider.set_handler(lambda texts: [[0.0, 0.0, 0.0, 0.0] for _ in texts])

    ingest_client_uploads(
        clients_root=clients_root,
        client_id="tenant_a",
        config_loader=_loader(clients_root),
        version_id="zero-v1",
        embedding_provider=provider,
    )

    assert not vector_index_path(clients_root, "tenant_a", "zero-v1").exists()
    chunks = json.loads(knowledge_index_path(clients_root, "tenant_a", "zero-v1").read_text())["chunks"]
    assert chunks[0]["embedding_status"] == "failed"
    assert chunks[0]["embedding_error_code"] == "ZERO_VECTOR"


def test_wrong_dim_vector_fails_validation() -> None:
    with pytest.raises(EmbeddingValidationError) as exc:
        validate_vector([0.1, 0.2], expected_dims=4)
    assert exc.value.code == "WRONG_DIM"


def test_cache_hit_avoids_second_provider_call(tmp_path: Path) -> None:
    clients_root = tmp_path / "clients"
    _write_client(clients_root, "tenant_a", ingestion_yaml="embed_enabled: true\n")
    uploads = clients_root / "tenant_a" / "uploads"
    (uploads / "cached.txt").write_text("cache me once", encoding="utf-8")
    provider = MockEmbeddingProvider(dim=4)

    ingest_client_uploads(
        clients_root=clients_root,
        client_id="tenant_a",
        config_loader=_loader(clients_root),
        version_id="cache-v1",
        embedding_provider=provider,
    )
    first_calls = provider.calls

    (uploads / "other.txt").write_text("different file", encoding="utf-8")
    provider2 = MockEmbeddingProvider(dim=4)
    ingest_client_uploads(
        clients_root=clients_root,
        client_id="tenant_a",
        config_loader=_loader(clients_root),
        version_id="cache-v2",
        embedding_provider=provider2,
    )

    assert first_calls == 1
    assert provider2.calls == 1
    report = json.loads(ingest_report_path(clients_root, "tenant_a", "cache-v2").read_text())
    assert report["embeddings_cached"] >= 1


def test_unchanged_source_carries_forward_without_reembedding(tmp_path: Path) -> None:
    clients_root = tmp_path / "clients"
    _write_client(clients_root, "tenant_a", ingestion_yaml="embed_enabled: true\n")
    uploads = clients_root / "tenant_a" / "uploads"
    (uploads / "stable.txt").write_text("stable unchanged body", encoding="utf-8")
    provider = MockEmbeddingProvider(dim=4)

    ingest_client_uploads(
        clients_root=clients_root,
        client_id="tenant_a",
        config_loader=_loader(clients_root),
        version_id="carry-v1",
        embedding_provider=provider,
    )
    activate_index(clients_root=clients_root, client_id="tenant_a")

    provider2 = MockEmbeddingProvider(dim=4)
    ingest_client_uploads(
        clients_root=clients_root,
        client_id="tenant_a",
        config_loader=_loader(clients_root),
        version_id="carry-v2",
        embedding_provider=provider2,
    )

    assert provider2.calls == 0
    sources = json.loads(source_manifest_path(clients_root, "tenant_a", "carry-v2").read_text())["sources"]
    assert sources[0]["status"] == "skipped_unchanged"
    report = json.loads(ingest_report_path(clients_root, "tenant_a", "carry-v2").read_text())
    assert report["embeddings_carried_forward"] == 1
    assert vector_index_path(clients_root, "tenant_a", "carry-v2").exists()


def test_changed_file_reembeds_only_changed_source(tmp_path: Path) -> None:
    clients_root = tmp_path / "clients"
    _write_client(clients_root, "tenant_a", ingestion_yaml="embed_enabled: true\n")
    uploads = clients_root / "tenant_a" / "uploads"
    (uploads / "stable.txt").write_text("stable unchanged body", encoding="utf-8")
    (uploads / "mutable.txt").write_text("version one mutable", encoding="utf-8")
    provider = MockEmbeddingProvider(dim=4)

    ingest_client_uploads(
        clients_root=clients_root,
        client_id="tenant_a",
        config_loader=_loader(clients_root),
        version_id="change-v1",
        embedding_provider=provider,
    )
    activate_index(clients_root=clients_root, client_id="tenant_a")

    (uploads / "mutable.txt").write_text("version two mutable changed", encoding="utf-8")
    provider2 = MockEmbeddingProvider(dim=4)
    ingest_client_uploads(
        clients_root=clients_root,
        client_id="tenant_a",
        config_loader=_loader(clients_root),
        version_id="change-v2",
        embedding_provider=provider2,
    )

    assert provider2.calls == 1
    assert len(provider2.seen_texts) == 1
    assert "version two" in provider2.seen_texts[0]


def test_mock_429_retries(tmp_path: Path) -> None:
    pool = EmbeddingKeyPool(keys=["key-a"])
    attempts = {"count": 0}

    def operation(_key: str) -> str:
        attempts["count"] += 1
        if attempts["count"] < 3:
            raise EmbeddingRateLimitError("429")
        return "ok"

    result = pool.call_with_retry(
        operation,
        max_retries=5,
        backoff_base_ms=1,
        backoff_max_ms=5,
    )
    assert result == "ok"
    assert attempts["count"] == 3


def test_quota_failure_rotates_to_next_key() -> None:
    pool = EmbeddingKeyPool(keys=["key-a", "key-b"])
    seen: list[str] = []

    def operation(key: str) -> str:
        seen.append(key)
        if key == "key-a":
            raise EmbeddingQuotaError("quota exceeded")
        return "ok"

    result = pool.call_with_retry(
        operation,
        max_retries=3,
        backoff_base_ms=1,
        backoff_max_ms=5,
    )
    assert result == "ok"
    assert seen == ["key-a", "key-b"]


def test_gemini_adapter_retries_rate_limit_with_embed_fn() -> None:
    pool = EmbeddingKeyPool(keys=["key-a"])
    calls = {"count": 0}

    def embed_fn(_key: str, texts: Sequence[str], _model: str) -> list[list[float]]:
        calls["count"] += 1
        if calls["count"] < 2:
            raise EmbeddingRateLimitError("429")
        return [[0.5, 0.6, 0.7, 0.8] for _ in texts]

    adapter = GeminiEmbeddingAdapter(
        pool,
        embed_fn=embed_fn,
        max_retries=3,
        backoff_base_ms=1,
        backoff_max_ms=5,
        expected_dims=4,
    )
    vectors = adapter.embed_texts(["hello"], model="test-model")
    assert vectors == [[0.5, 0.6, 0.7, 0.8]]
    assert calls["count"] == 2


def test_rollback_index_moves_active_to_previous(tmp_path: Path) -> None:
    clients_root = tmp_path / "clients"
    _write_client(clients_root, "tenant_a")
    uploads = clients_root / "tenant_a" / "uploads"

    (uploads / "v1.txt").write_text("rollback version one", encoding="utf-8")
    ingest_client_uploads(
        clients_root=clients_root,
        client_id="tenant_a",
        config_loader=_loader(clients_root),
        version_id="rollback-v1",
    )
    activate_index(clients_root=clients_root, client_id="tenant_a")

    (uploads / "v2.txt").write_text("rollback version two", encoding="utf-8")
    ingest_client_uploads(
        clients_root=clients_root,
        client_id="tenant_a",
        config_loader=_loader(clients_root),
        version_id="rollback-v2",
    )
    activate_index(clients_root=clients_root, client_id="tenant_a")

    rolled = rollback_index(clients_root=clients_root, client_id="tenant_a")
    assert rolled == "rollback-v1"


def test_structured_extraction_error_for_missing_dependency(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from packages.adapters.ingestion import local_upload_extractor as extractor

    monkeypatch.setattr(
        extractor,
        "_extract_pdf",
        lambda _data: extractor.ExtractionResult(
            unsupported=True,
            reason="pdf extraction unavailable (install pypdf)",
            error_stage="pdf",
            error_code="DEPENDENCY_MISSING",
            error_detail="pdf extraction unavailable (install pypdf)",
            dependency_missing=True,
        ),
    )

    clients_root = tmp_path / "clients"
    _write_client(
        clients_root,
        "tenant_a",
        ingestion_yaml="allowed_extensions:\n  - .pdf\n",
    )
    (clients_root / "tenant_a" / "uploads" / "report.pdf").write_bytes(b"%PDF-1.4 fake")

    ingest_client_uploads(
        clients_root=clients_root,
        client_id="tenant_a",
        config_loader=_loader(clients_root),
        version_id="pdf-dep-v1",
    )

    sources = json.loads(source_manifest_path(clients_root, "tenant_a", "pdf-dep-v1").read_text())["sources"]
    record = sources[0]
    assert record["status"] == "unsupported"
    assert record["error_code"] == "DEPENDENCY_MISSING"
    assert record["dependency_missing"] is True
    assert record["error_stage"] == "pdf"
    report = json.loads(ingest_report_path(clients_root, "tenant_a", "pdf-dep-v1").read_text())
    assert report["extraction_errors_by_stage"].get("pdf", 0) >= 1
