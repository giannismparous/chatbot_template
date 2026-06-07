from __future__ import annotations

from pathlib import Path

from packages.core.tenant.paths import client_root, safe_client_id


def client_web_cache_dir(clients_root: Path, client_id: str) -> Path:
    return client_root(clients_root, safe_client_id(client_id)) / "web_cache"


def web_cache_pages_dir(clients_root: Path, client_id: str) -> Path:
    return client_web_cache_dir(clients_root, client_id) / "pages"


def crawl_manifest_path(clients_root: Path, client_id: str) -> Path:
    return client_web_cache_dir(clients_root, client_id) / "crawl_manifest.json"


def crawl_manifest_key() -> str:
    return "web_cache/crawl_manifest.json"


def web_cache_pages_prefix() -> str:
    return "web_cache/pages"



def web_sources_config_path(config_dir: Path) -> Path:
    return config_dir / "web_sources.yaml"
