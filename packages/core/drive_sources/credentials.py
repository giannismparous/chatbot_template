from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path


@dataclass
class DriveCredentialsInfo:
    configured: bool
    service_account_email: str | None = None
    error: str | None = None


def load_drive_credentials_info() -> DriveCredentialsInfo:
    path = (os.getenv("GOOGLE_DRIVE_CREDENTIALS_JSON") or "").strip()
    if not path:
        return DriveCredentialsInfo(
            configured=False,
            error="GOOGLE_DRIVE_CREDENTIALS_JSON is not set.",
        )
    cred_path = Path(path)
    if not cred_path.is_file():
        return DriveCredentialsInfo(
            configured=False,
            error=f"Credentials file not found: {path}",
        )
    try:
        raw = json.loads(cred_path.read_text(encoding="utf-8"))
    except Exception as exc:
        return DriveCredentialsInfo(
            configured=False,
            error=f"Invalid credentials JSON: {exc}",
        )
    email = str(raw.get("client_email") or "").strip() or None
    return DriveCredentialsInfo(configured=True, service_account_email=email)


def build_drive_service(credentials_path: str):
    from google.oauth2 import service_account
    from googleapiclient.discovery import build

    scopes = ["https://www.googleapis.com/auth/drive.readonly"]
    creds = service_account.Credentials.from_service_account_file(credentials_path, scopes=scopes)
    return build("drive", "v3", credentials=creds, cache_discovery=False)
