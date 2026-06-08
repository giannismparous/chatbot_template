from __future__ import annotations

import fnmatch
import hashlib
from pathlib import Path
from typing import Any

from packages.adapters.embedding.gemini_embedding_adapter import GeminiEmbeddingAdapter
from packages.adapters.ingestion.local_upload_extractor import extract_text, file_extension
from packages.core.config.loader import TenantConfigLoader
from packages.core.ingestion.chunking import chunk_text
from packages.core.ingestion.embeddings import chunk_content_hash, embed_pending_chunks
from packages.core.ingestion.manifest import (
    set_pending_version_storage,
    write_ingest_report_storage,
    write_knowledge_index_storage,
    write_source_manifest_storage,
    write_vector_index_storage,
)
from packages.core.ingestion.models import (
    IngestReport,
    IngestionSettings,
    IngestResult,
    KnowledgeChunk,
    SourceRecord,
    utc_now_iso,
)
from packages.core.ingestion.nfc import normalize_filename_nfc, normalize_text_nfc
from packages.core.ingestion.paths import (
    client_uploads_dir,
    client_versions_dir,
)
from packages.core.storage.resolve import resolve_storage
from packages.core.storage.tenant_storage import TenantStorage
from packages.core.ingestion.source_diff import find_unchanged_source, load_active_snapshot
from packages.core.ingestion.source_mapping import (
    apply_mapping_to_chunk,
    load_source_mapping,
)
from packages.core.ports.embedding_provider import EmbeddingProvider
from packages.core.tenant.paths import client_config_dir, safe_client_id


def load_ingestion_settings(config_loader: TenantConfigLoader, client_id: str) -> IngestionSettings:
    merged = config_loader.load(client_id)
    return IngestionSettings.from_dict(merged.ingestion)


def should_skip_file(filename: str, skip_patterns: list[str]) -> bool:
    name = normalize_filename_nfc(filename)
    return any(fnmatch.fnmatch(name, pattern) for pattern in skip_patterns)


def _content_hash(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _source_id(relative_path: str, content_hash: str) -> str:
    digest = hashlib.sha256(f"{relative_path}:{content_hash}".encode("utf-8")).hexdigest()
    return f"src-{digest[:12]}"


def _relative_upload_path(uploads_root: Path, file_path: Path) -> str:
    rel = file_path.relative_to(uploads_root).as_posix()
    parts = [normalize_filename_nfc(part) for part in rel.split("/")]
    return "/".join(parts)


def _iter_upload_files(uploads_dir: Path) -> list[Path]:
    if not uploads_dir.is_dir():
        return []
    files: list[Path] = []
    for path in sorted(uploads_dir.rglob("*")):
        if path.is_file():
            files.append(path)
    return files


def _build_embedding_provider(settings: IngestionSettings) -> EmbeddingProvider:
    return GeminiEmbeddingAdapter.from_env(
        max_retries=settings.embed_max_retries,
        backoff_base_ms=settings.embed_backoff_base_ms,
        backoff_max_ms=settings.embed_backoff_max_ms,
    )


def _chunk_from_prior(raw: dict) -> KnowledgeChunk:
    return KnowledgeChunk(
        id=str(raw.get("id", "")),
        source_id=str(raw.get("source_id", "")),
        title=str(raw.get("title", "")),
        content=str(raw.get("content", "")),
        internal_url=str(raw.get("internal_url", "")),
        citation_url=raw.get("citation_url"),
        source_visibility=raw.get("source_visibility", "internal"),
        language=str(raw.get("language", "unknown")),
        content_hash=str(raw.get("content_hash") or chunk_content_hash(str(raw.get("content", "")))),
        embedding_status="skipped_unchanged",
        embedding_model=raw.get("embedding_model"),
    )


def ingest_client_uploads(
    *,
    clients_root: Path,
    client_id: str,
    config_loader: TenantConfigLoader,
    version_id: str | None = None,
    embedding_provider: EmbeddingProvider | None = None,
    storage: TenantStorage | None = None,
    skip_runtime_hydration: bool = False,
) -> IngestResult:
    cid = safe_client_id(client_id)
    if not skip_runtime_hydration:
        from packages.core.storage.drive_cache_hydrator import ensure_firebase_ingest_assets_hydrated

        ensure_firebase_ingest_assets_hydrated(client_id=cid)
    store = resolve_storage(clients_root=clients_root, storage=storage)
    clients_root = store.clients_root()
    settings = load_ingestion_settings(config_loader, cid)
    uploads_dir = client_uploads_dir(clients_root, cid)
    versions_dir = client_versions_dir(clients_root, cid)
    versions_dir.mkdir(parents=True, exist_ok=True)

    vid = version_id or utc_now_iso().replace(":", "").replace("+", "_")
    version_key_prefix = f"indexes/versions/{vid}"
    if store.exists(cid, f"{version_key_prefix}/knowledge_index.json"):
        raise FileExistsError(f"Version already exists: {vid}")

    store.ensure_prefix(cid, version_key_prefix)

    active_snapshot = load_active_snapshot(clients_root, cid) if settings.skip_unchanged_sources else None
    merged_config = config_loader.load(cid)
    source_mapping = load_source_mapping(client_config_dir(clients_root, cid))
    source_whitelist = merged_config.source_whitelist or {}
    chunks: list[KnowledgeChunk] = []
    sources: list[SourceRecord] = []
    carried_vectors: dict[str, list[float]] = {}
    chunk_seq = 0
    extraction_errors_by_stage: dict[str, int] = {}

    allowed = {ext.lower() if ext.startswith(".") else f".{ext.lower()}" for ext in settings.allowed_extensions}

    for file_path in _iter_upload_files(uploads_dir):
        rel_path = _relative_upload_path(uploads_dir, file_path)
        filename = normalize_filename_nfc(file_path.name)
        ext = file_extension(filename)
        internal_url = f"uploads/{rel_path}"

        if should_skip_file(filename, settings.skip_files):
            sources.append(
                SourceRecord(
                    source_id=_source_id(rel_path, "skipped"),
                    filename=filename,
                    path=internal_url,
                    content_hash=None,
                    status="skipped",
                    reason="matched skip_files pattern",
                    indexed_at=None,
                    chunk_count=0,
                )
            )
            continue

        if ext not in allowed:
            sources.append(
                SourceRecord(
                    source_id=_source_id(rel_path, "unsupported"),
                    filename=filename,
                    path=internal_url,
                    content_hash=None,
                    status="unsupported",
                    reason=f"extension {ext!r} not in allowed_extensions",
                    indexed_at=None,
                    chunk_count=0,
                    error_stage="extract",
                    error_code="EXTENSION_NOT_ALLOWED",
                    error_detail=f"extension {ext!r} not in allowed_extensions",
                )
            )
            extraction_errors_by_stage["extract"] = extraction_errors_by_stage.get("extract", 0) + 1
            continue

        try:
            raw_bytes = file_path.read_bytes()
            content_hash = _content_hash(raw_bytes)
            source_id = _source_id(rel_path, content_hash)

            unchanged = find_unchanged_source(
                active_snapshot,
                internal_path=internal_url,
                content_hash=content_hash,
            )
            if unchanged is not None and active_snapshot is not None:
                prior_chunks = active_snapshot.chunks_by_source_id.get(str(unchanged.get("source_id", "")), [])
                if prior_chunks:
                    indexed_at = utc_now_iso()
                    for raw_chunk in prior_chunks:
                        chunk = _chunk_from_prior(raw_chunk)
                        apply_mapping_to_chunk(
                            chunk,
                            rel_path=rel_path,
                            filename=filename,
                            mapping=source_mapping,
                            whitelist=source_whitelist,
                        )
                        chunks.append(chunk)
                        vector = active_snapshot.vectors_by_chunk_id.get(chunk.id)
                        if vector:
                            carried_vectors[chunk.id] = vector
                    sources.append(
                        SourceRecord(
                            source_id=str(unchanged.get("source_id", source_id)),
                            filename=filename,
                            path=internal_url,
                            content_hash=content_hash,
                            status="skipped_unchanged",
                            reason="content hash unchanged since active version",
                            indexed_at=indexed_at,
                            chunk_count=len(prior_chunks),
                        )
                    )
                    continue

            extracted = extract_text(file_path, raw_bytes)
            if extracted.unsupported:
                stage = extracted.error_stage or "extract"
                extraction_errors_by_stage[stage] = extraction_errors_by_stage.get(stage, 0) + 1
                sources.append(
                    SourceRecord(
                        source_id=source_id,
                        filename=filename,
                        path=internal_url,
                        content_hash=content_hash,
                        status="unsupported",
                        reason=extracted.reason or extracted.error_detail or "unsupported format",
                        indexed_at=None,
                        chunk_count=0,
                        error_stage=extracted.error_stage,
                        error_code=extracted.error_code,
                        error_detail=extracted.error_detail or extracted.reason,
                        dependency_missing=extracted.dependency_missing,
                    )
                )
                continue

            if extracted.error:
                stage = extracted.error_stage or "extract"
                extraction_errors_by_stage[stage] = extraction_errors_by_stage.get(stage, 0) + 1
                sources.append(
                    SourceRecord(
                        source_id=source_id,
                        filename=filename,
                        path=internal_url,
                        content_hash=content_hash,
                        status="failed",
                        reason=extracted.error,
                        indexed_at=None,
                        chunk_count=0,
                        error_stage=extracted.error_stage,
                        error_code=extracted.error_code,
                        error_detail=extracted.error_detail or extracted.error,
                        dependency_missing=extracted.dependency_missing,
                    )
                )
                continue

            normalized_text = normalize_text_nfc(extracted.text or "")
            text_chunks = chunk_text(
                normalized_text,
                chunk_size=settings.chunk_size,
                overlap=settings.overlap,
            )
            if not text_chunks:
                sources.append(
                    SourceRecord(
                        source_id=source_id,
                        filename=filename,
                        path=internal_url,
                        content_hash=content_hash,
                        status="skipped",
                        reason="empty content after extraction",
                        indexed_at=None,
                        chunk_count=0,
                        error_stage="extract",
                        error_code="EMPTY_CONTENT",
                        error_detail="empty content after extraction",
                    )
                )
                extraction_errors_by_stage["extract"] = extraction_errors_by_stage.get("extract", 0) + 1
                continue

            indexed_at = utc_now_iso()
            source_chunks: list[KnowledgeChunk] = []
            for piece in text_chunks:
                chunk_seq += 1
                content = piece
                source_chunks.append(
                    KnowledgeChunk(
                        id=f"chunk-{chunk_seq:05d}",
                        source_id=source_id,
                        title=filename,
                        content=content,
                        internal_url=internal_url,
                        citation_url=None,
                        source_visibility="internal",
                        language=extracted.language or "unknown",
                        content_hash=chunk_content_hash(content),
                        embedding_status="not_embedded",
                    )
                )
            for chunk in source_chunks:
                apply_mapping_to_chunk(
                    chunk,
                    rel_path=rel_path,
                    filename=filename,
                    mapping=source_mapping,
                    whitelist=source_whitelist,
                )
            chunks.extend(source_chunks)

            sources.append(
                SourceRecord(
                    source_id=source_id,
                    filename=filename,
                    path=internal_url,
                    content_hash=content_hash,
                    status="indexed",
                    reason=None,
                    indexed_at=indexed_at,
                    chunk_count=len(source_chunks),
                )
            )
        except Exception as exc:
            sources.append(
                SourceRecord(
                    source_id=_source_id(rel_path, "failed"),
                    filename=filename,
                    path=internal_url,
                    content_hash=None,
                    status="failed",
                    reason=str(exc),
                    indexed_at=None,
                    chunk_count=0,
                    error_stage="extract",
                    error_code="UNEXPECTED_ERROR",
                    error_detail=str(exc),
                )
            )
            extraction_errors_by_stage["extract"] = extraction_errors_by_stage.get("extract", 0) + 1

    from packages.core.ingestion.web_ingest import ingest_web_cache_sources

    chunk_seq = ingest_web_cache_sources(
        clients_root=clients_root,
        client_id=cid,
        config_loader=config_loader,
        settings=settings,
        active_snapshot=active_snapshot,
        chunk_seq=chunk_seq,
        chunks=chunks,
        sources=sources,
        carried_vectors=carried_vectors,
        extraction_errors_by_stage=extraction_errors_by_stage,
        chunk_from_prior=_chunk_from_prior,
    )

    from packages.core.ingestion.drive_ingest import ingest_drive_cache_sources

    chunk_seq = ingest_drive_cache_sources(
        clients_root=clients_root,
        client_id=cid,
        config_loader=config_loader,
        settings=settings,
        active_snapshot=active_snapshot,
        chunk_seq=chunk_seq,
        chunks=chunks,
        sources=sources,
        carried_vectors=carried_vectors,
        extraction_errors_by_stage=extraction_errors_by_stage,
        chunk_from_prior=_chunk_from_prior,
    )

    embedding_stats = None
    vector_count = 0
    if settings.embed_enabled:
        provider = embedding_provider or _build_embedding_provider(settings)
        embed_result = embed_pending_chunks(
            clients_root=clients_root,
            client_id=cid,
            chunks=chunks,
            carried_vectors=carried_vectors,
            settings=settings,
            provider=provider,
        )
        embedding_stats = embed_result.stats
        if embed_result.vectors_by_chunk_id and embed_result.embedding_dims:
            source_by_chunk = {c.id: c.source_id for c in chunks}
            vector_entries = [
                {
                    "chunk_id": chunk_id,
                    "source_id": source_by_chunk[chunk_id],
                    "embedding": vector,
                }
                for chunk_id, vector in embed_result.vectors_by_chunk_id.items()
                if chunk_id in source_by_chunk
            ]
            write_vector_index_storage(
                store,
                cid,
                version_id=vid,
                embedding_model=settings.embedding_model,
                embedding_dims=embed_result.embedding_dims,
                vectors=vector_entries,
            )
            vector_count = len(vector_entries)
    else:
        for chunk in chunks:
            if chunk.embedding_status == "skipped_unchanged":
                continue
            chunk.embedding_status = "not_embedded"
            chunk.embedding_model = None

    write_knowledge_index_storage(
        store,
        cid,
        version_id=vid,
        chunks=chunks,
    )
    write_source_manifest_storage(
        store,
        cid,
        version_id=vid,
        sources=sources,
    )

    indexed = sum(1 for s in sources if s.status == "indexed")
    skipped = sum(1 for s in sources if s.status == "skipped")
    skipped_unchanged = sum(1 for s in sources if s.status == "skipped_unchanged")
    unsupported = sum(1 for s in sources if s.status == "unsupported")
    failed = sum(1 for s in sources if s.status == "failed")

    report = IngestReport(
        client_id=cid,
        version_id=vid,
        embed_enabled=settings.embed_enabled,
        sources_total=len(sources),
        indexed=indexed,
        skipped=skipped,
        skipped_unchanged=skipped_unchanged,
        unsupported=unsupported,
        failed=failed,
        chunks_total=len(chunks),
        embeddings_embedded=embedding_stats.embedded if embedding_stats else 0,
        embeddings_cached=embedding_stats.cached if embedding_stats else 0,
        embeddings_carried_forward=embedding_stats.carried_forward if embedding_stats else 0,
        embeddings_failed=embedding_stats.failed if embedding_stats else 0,
        provider_calls=embedding_stats.provider_calls if embedding_stats else 0,
        extraction_errors_by_stage=extraction_errors_by_stage,
    )
    write_ingest_report_storage(store, cid, vid, report)
    set_pending_version_storage(store, cid, vid)

    return IngestResult(
        client_id=cid,
        version_id=vid,
        chunk_count=len(chunks),
        source_count=len(sources),
        indexed_count=indexed,
        skipped_count=skipped,
        skipped_unchanged_count=skipped_unchanged,
        unsupported_count=unsupported,
        failed_count=failed,
        embed_enabled=settings.embed_enabled,
        vector_count=vector_count,
    )
