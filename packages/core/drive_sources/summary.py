from __future__ import annotations

from collections import Counter

from packages.core.drive_sources.models import DriveFileRecord, DriveSourceRuntimeStatus

DOCX_SETUP_MESSAGE = "DOCX extraction unavailable. Run pip install -r requirements.txt."


def normalize_file_error(error: str | None) -> str:
    if not error:
        return "unknown"
    lowered = error.lower()
    if "python-docx" in lowered or "docx extraction unavailable" in lowered:
        return DOCX_SETUP_MESSAGE
    if error.startswith("unsupported_mime:"):
        return "unsupported file type"
    if error == "file_too_large":
        return "file too large"
    if error == "empty_extraction":
        return "empty extraction"
    if error == "trashed":
        return "trashed"
    if error.startswith("download_failed:"):
        return "download failed"
    if "dependency_missing" in lowered:
        return DOCX_SETUP_MESSAGE
    return error


def failure_breakdown(files: dict[str, DriveFileRecord]) -> dict[str, int]:
    counts: Counter[str] = Counter()
    for record in files.values():
        if record.status in {"failed_extraction", "failed_size", "failed_unsupported"}:
            key = normalize_file_error(record.error)
            counts[key] += 1
    return dict(sorted(counts.items(), key=lambda item: (-item[1], item[0])))


def compute_source_status(
    *,
    synced: int,
    failed: int,
    skipped_unchanged: int,
    files: dict[str, DriveFileRecord],
) -> DriveSourceRuntimeStatus:
    if synced > 0 and failed > 0:
        return "synced_with_warnings"
    if synced > 0:
        return "synced"
    if any(f.status == "failed_extraction" for f in files.values()):
        return "failed_extraction"
    if failed > 0:
        return "failed_extraction"
    if skipped_unchanged > 0:
        return "synced"
    return "configured"


def build_sync_summary(
    *,
    status: str,
    files_discovered: int,
    files_synced: int,
    files_skipped_unchanged: int,
    files_failed: int,
    failure_breakdown: dict[str, int],
) -> str:
    if status == "failed_auth":
        return "Drive sync failed: authentication error."
    if status == "failed_extraction" and files_synced == 0:
        return f"Sync failed: {files_failed} file(s) could not be extracted."

    parts = [f"{files_discovered} discovered"]
    if files_synced:
        parts.append(f"{files_synced} fetched")
    if files_skipped_unchanged:
        parts.append(f"{files_skipped_unchanged} skipped unchanged")
    if files_failed:
        parts.append(f"{files_failed} failed")

    prefix = "Synced with warnings" if status == "synced_with_warnings" else "Sync completed"
    summary = f"{prefix}: {', '.join(parts)}."
    if failure_breakdown:
        grouped = "; ".join(f"{count} {reason}" for reason, count in failure_breakdown.items())
        summary = f"{summary} Failures: {grouped}."
    return summary
