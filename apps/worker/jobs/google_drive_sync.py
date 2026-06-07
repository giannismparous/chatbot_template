from __future__ import annotations

import io
import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, Iterable, List

from dotenv import load_dotenv
from google.oauth2 import service_account
from googleapiclient.discovery import build
from googleapiclient.http import MediaIoBaseDownload

from packages.config.loaders import load_yaml

load_dotenv()

ROOT = Path(__file__).resolve().parents[3]
DRIVE_CFG_PATH = ROOT / "packages" / "config" / "defaults" / "drive_sources.yaml"
INDEX_PATH = ROOT / "packages" / "config" / "defaults" / "google_drive_index.json"
SCOPES = ["https://www.googleapis.com/auth/drive.readonly"]


def _chunk_text(text: str, chunk_size: int, overlap: int) -> Iterable[str]:
    cleaned = " ".join(text.split())
    if not cleaned:
        return []
    start = 0
    chunks: List[str] = []
    while start < len(cleaned):
        end = min(len(cleaned), start + chunk_size)
        chunks.append(cleaned[start:end])
        if end >= len(cleaned):
            break
        start = max(start + 1, end - overlap)
    return chunks


def _get_drive_service(credentials_path: str):
    creds = service_account.Credentials.from_service_account_file(credentials_path, scopes=SCOPES)
    return build("drive", "v3", credentials=creds, cache_discovery=False)


def _list_files(service, folder_id: str, include_shared_drives: bool) -> List[Dict]:
    q = f"'{folder_id}' in parents and trashed = false"
    fields = "nextPageToken, files(id,name,mimeType,webViewLink)"
    page_token = None
    files: List[Dict] = []
    while True:
        resp = (
            service.files()
            .list(
                q=q,
                fields=fields,
                pageToken=page_token,
                supportsAllDrives=include_shared_drives,
                includeItemsFromAllDrives=include_shared_drives,
                pageSize=200,
            )
            .execute()
        )
        files.extend(resp.get("files", []))
        page_token = resp.get("nextPageToken")
        if not page_token:
            break
    return files


def _walk_files(service, root_folder_id: str, include_shared_drives: bool, recursive: bool) -> List[Dict]:
    queue = [root_folder_id]
    visited = set()
    gathered: List[Dict] = []
    folder_mime = "application/vnd.google-apps.folder"
    while queue:
        folder_id = queue.pop(0)
        if folder_id in visited:
            continue
        visited.add(folder_id)
        items = _list_files(service, folder_id, include_shared_drives)
        for item in items:
            if item.get("mimeType") == folder_mime and recursive:
                queue.append(item["id"])
                continue
            gathered.append(item)
    return gathered


def _download_text(service, file_id: str, mime_type: str) -> str:
    if mime_type == "application/vnd.google-apps.document":
        req = service.files().export_media(fileId=file_id, mimeType="text/plain")
    else:
        req = service.files().get_media(fileId=file_id)
    fh = io.BytesIO()
    downloader = MediaIoBaseDownload(fh, req)
    done = False
    while not done:
        _, done = downloader.next_chunk()
    return fh.getvalue().decode("utf-8", errors="ignore")


def run_google_drive_sync(client_id: str = "default") -> int:
    credentials_path = os.getenv("GOOGLE_DRIVE_CREDENTIALS_JSON", "").strip()
    if not credentials_path:
        print("GOOGLE_DRIVE_CREDENTIALS_JSON is not configured. Skipping Drive sync.")
        return 0

    cfg = load_yaml(str(DRIVE_CFG_PATH))
    defaults = cfg.get("defaults", {})
    client_cfg = cfg.get("clients", {}).get(client_id, {})
    roots = client_cfg.get("roots", [])
    if not roots:
        print(f"No Drive roots configured for client '{client_id}'.")
        return 0

    chunk_size = int(defaults.get("chunk_size", 1200))
    overlap = int(defaults.get("overlap", 150))
    include_shared_drives = bool(defaults.get("include_shared_drives", True))
    recursive = bool(defaults.get("recursive", True))
    allowed_mimes = set(defaults.get("mime_types", []))

    service = _get_drive_service(credentials_path)
    documents = []
    indexed_count = 0

    for root in roots:
        folder_id = (root.get("id") or "").strip()
        if not folder_id:
            continue
        for f in _walk_files(service, folder_id, include_shared_drives, recursive):
            mime_type = f.get("mimeType", "")
            if allowed_mimes and mime_type not in allowed_mimes:
                continue
            try:
                text = _download_text(service, f["id"], mime_type)
            except Exception as exc:
                print(f"Failed to extract file {f.get('name','unknown')}: {exc}")
                continue
            for idx, chunk in enumerate(_chunk_text(text, chunk_size, overlap)):
                documents.append(
                    {
                        "id": f"{f['id']}::{idx}",
                        "file_id": f["id"],
                        "title": f.get("name", "Untitled"),
                        "content": chunk,
                        "url": f.get("webViewLink", ""),
                        "source": "google_drive",
                    }
                )
                indexed_count += 1

    payload = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "client_id": client_id,
        "documents": documents,
    }
    INDEX_PATH.parent.mkdir(parents=True, exist_ok=True)
    INDEX_PATH.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"Drive sync complete. Indexed chunks: {indexed_count}")
    return indexed_count


if __name__ == "__main__":
    run_google_drive_sync()
