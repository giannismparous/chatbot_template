from __future__ import annotations

import hashlib
import logging
from dataclasses import dataclass, field
from pathlib import Path

from packages.core.config.loader import TenantConfigLoader
from packages.core.drive_sources.citation import apply_drive_citation_to_chunk
from packages.core.drive_sources.config import load_drive_sources
from packages.core.drive_sources.manifest import load_drive_sync_manifest
from packages.core.drive_sources.paths import drive_cache_files_dir, drive_sync_manifest_path
from packages.core.ingestion.chunking import chunk_text
from packages.core.ingestion.embeddings import chunk_content_hash
from packages.core.ingestion.models import KnowledgeChunk, SourceRecord, utc_now_iso
from packages.core.ingestion.nfc import normalize_text_nfc
from packages.core.ingestion.source_diff import find_unchanged_source
from packages.core.ingestion.source_mapping import load_source_mapping
from packages.core.storage.drive_cache_hydrator import drive_file_indexable
from packages.core.tenant.paths import client_config_dir

logger = logging.getLogger(__name__)


@dataclass
class DriveIngestStats:
    manifest_loaded: bool = False
    files_discovered: int = 0
    indexable: int = 0
    skipped_by_status: dict[str, int] = field(default_factory=dict)
    missing_cache_file: int = 0
    empty_content: int = 0
    chunks_before: int = 0
    chunks_after: int = 0
    sources_before: int = 0
    sources_after: int = 0


def _drive_internal_url(source_id: str, file_key: str) -> str:
    return f"internal://drive/{source_id}/{file_key}"


def _drive_source_id(source_id: str, content_hash: str) -> str:
    digest = hashlib.sha256(f"drive:{source_id}:{content_hash}".encode("utf-8")).hexdigest()
    return f"src-{digest[:12]}"


def ingest_drive_cache_sources(
    *,
    clients_root: Path,
    client_id: str,
    config_loader: TenantConfigLoader,
    settings,
    active_snapshot,
    chunk_seq: int,
    chunks: list[KnowledgeChunk],
    sources: list[SourceRecord],
    carried_vectors: dict[str, list[float]],
    extraction_errors_by_stage: dict[str, int],
    chunk_from_prior,
) -> int:
    stats = DriveIngestStats(
        chunks_before=len(chunks),
        sources_before=len(sources),
    )
    config_dir = client_config_dir(clients_root, client_id)
    drive_config = load_drive_sources(config_dir)
    manifest_path = drive_sync_manifest_path(clients_root, client_id)
    stats.manifest_loaded = manifest_path.is_file()
    manifest = load_drive_sync_manifest(clients_root, client_id)
    mapping = load_source_mapping(config_dir)
    merged = config_loader.load(client_id)
    whitelist = merged.source_whitelist or {}
    files_root = drive_cache_files_dir(clients_root, client_id)

    if not stats.manifest_loaded:
        logger.info(
            "Drive ingest client=%s manifest_loaded=no enabled_sources=%s",
            client_id,
            sum(1 for s in drive_config.sources if s.enabled),
        )
        return chunk_seq

    for source in drive_config.sources:
        if not source.enabled:
            continue
        sync_record = manifest.sources.get(source.id)
        if sync_record is None:
            continue
        source_files_dir = files_root / source.id
        if not source_files_dir.is_dir():
            logger.warning(
                "Drive ingest client=%s source=%s cache_dir_missing=%s",
                client_id,
                source.id,
                source_files_dir,
            )
            continue

        for file in sync_record.files.values():
            stats.files_discovered += 1
            if not drive_file_indexable(file):
                stats.skipped_by_status[file.status] = stats.skipped_by_status.get(file.status, 0) + 1
                continue
            stats.indexable += 1
            text_path = source_files_dir / file.cache_file
            if not text_path.is_file():
                stats.missing_cache_file += 1
                logger.warning(
                    "Drive ingest client=%s source=%s cache_file_missing=%s",
                    client_id,
                    source.id,
                    file.cache_file,
                )
                continue

            text = normalize_text_nfc(text_path.read_text(encoding="utf-8"))
            content_hash = hashlib.sha256(text.encode("utf-8")).hexdigest()
            file_key = Path(file.cache_file).stem
            internal_url = _drive_internal_url(source.id, file_key)
            source_id = _drive_source_id(source.id, content_hash)
            display_title = file.name or source.title or source.id

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
                        chunk = chunk_from_prior(raw_chunk)
                        apply_drive_citation_to_chunk(
                            chunk,
                            source_id=source.id,
                            file_key=file_key,
                            title=display_title,
                            mapping=mapping,
                            whitelist=whitelist,
                        )
                        chunks.append(chunk)
                        vector = active_snapshot.vectors_by_chunk_id.get(chunk.id)
                        if vector:
                            carried_vectors[chunk.id] = vector
                    sources.append(
                        SourceRecord(
                            source_id=str(unchanged.get("source_id", source_id)),
                            filename=f"{source.id}/{file.cache_file}",
                            path=internal_url,
                            content_hash=content_hash,
                            status="skipped_unchanged",
                            reason="drive content hash unchanged since active version",
                            indexed_at=indexed_at,
                            chunk_count=len(prior_chunks),
                        )
                    )
                    continue

            text_chunks = chunk_text(text, chunk_size=settings.chunk_size, overlap=settings.overlap)
            if not text_chunks:
                stats.empty_content += 1
                sources.append(
                    SourceRecord(
                        source_id=source_id,
                        filename=f"{source.id}/{file.cache_file}",
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
                source_chunks.append(
                    KnowledgeChunk(
                        id=f"chunk-{chunk_seq:05d}",
                        source_id=source_id,
                        title=display_title,
                        content=piece,
                        internal_url=internal_url,
                        citation_url=None,
                        source_visibility="internal",
                        language="unknown",
                        content_hash=chunk_content_hash(piece),
                        embedding_status="not_embedded",
                    )
                )
            for chunk in source_chunks:
                apply_drive_citation_to_chunk(
                    chunk,
                    source_id=source.id,
                    file_key=file_key,
                    title=display_title,
                    mapping=mapping,
                    whitelist=whitelist,
                )
            chunks.extend(source_chunks)
            sources.append(
                SourceRecord(
                    source_id=source_id,
                    filename=f"{source.id}/{file.cache_file}",
                    path=internal_url,
                    content_hash=content_hash,
                    status="indexed",
                    reason=None,
                    indexed_at=indexed_at,
                    chunk_count=len(source_chunks),
                )
            )

    stats.chunks_after = len(chunks)
    stats.sources_after = len(sources)
    logger.info(
        "Drive ingest client=%s manifest_loaded=%s discovered=%s indexable=%s "
        "skipped_by_status=%s missing_cache_file=%s empty_content=%s "
        "sources=%s->%s chunks=%s->%s",
        client_id,
        stats.manifest_loaded,
        stats.files_discovered,
        stats.indexable,
        stats.skipped_by_status,
        stats.missing_cache_file,
        stats.empty_content,
        stats.sources_before,
        stats.sources_after,
        stats.chunks_before,
        stats.chunks_after,
    )
    return chunk_seq
