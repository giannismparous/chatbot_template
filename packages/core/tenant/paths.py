from __future__ import annotations

import re
from pathlib import Path

_CLIENT_ID_PATTERN = re.compile(r"^[a-zA-Z0-9][a-zA-Z0-9_-]{0,63}$")


def safe_client_id(client_id: str) -> str:
    """Reject path traversal and invalid tenant ids."""
    normalized = (client_id or "").strip()
    if not normalized or not _CLIENT_ID_PATTERN.fullmatch(normalized):
        raise ValueError(f"Invalid client_id: {client_id!r}")
    if ".." in normalized or "/" in normalized or "\\" in normalized:
        raise ValueError(f"Invalid client_id: {client_id!r}")
    return normalized


def client_root(clients_root: Path, client_id: str) -> Path:
    cid = safe_client_id(client_id)
    root = clients_root.resolve()
    path = (root / cid).resolve()
    if not str(path).startswith(str(root)):
        raise ValueError(f"client_id escapes tenant root: {client_id!r}")
    return path


def client_config_dir(clients_root: Path, client_id: str) -> Path:
    return client_root(clients_root, client_id) / "config"


def domain_pack_dir(domain_packs_root: Path, pack_id: str) -> Path:
    """Resolve domain pack path; reject traversal outside domain_packs_root."""
    pid = safe_client_id(pack_id)
    root = domain_packs_root.resolve()
    path = (root / pid).resolve()
    if not str(path).startswith(str(root)):
        raise ValueError(f"domain_pack escapes pack root: {pack_id!r}")
    if path == root:
        raise ValueError(f"Invalid domain_pack: {pack_id!r}")
    return path
