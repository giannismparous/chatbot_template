from __future__ import annotations

import json
import urllib.parse
import urllib.request
from typing import List

from packages.config.loaders import load_yaml
from packages.core.domain.interfaces import KnowledgeConnector
from packages.core.domain.models import RetrievedChunk


class APIConnector(KnowledgeConnector):
    def __init__(
        self,
        base_url: str,
        config_path: str,
        api_key: str = "",
        client_id: str = "default",
    ) -> None:
        self._base_url = base_url.rstrip("/")
        self._config_path = config_path
        self._api_key = api_key.strip()
        self._client_id = client_id

    def _build_request_url(self, query: str, limit: int) -> str:
        cfg = load_yaml(self._config_path)
        defaults = cfg.get("defaults", {})
        client_cfg = cfg.get("clients", {}).get(self._client_id, {})
        if not client_cfg.get("enabled", False) or not self._base_url:
            return ""
        endpoint = client_cfg.get("endpoint_path", defaults.get("endpoint_path", "/search"))
        query_param = client_cfg.get("query_param", defaults.get("query_param", "q"))
        limit_param = client_cfg.get("limit_param", defaults.get("limit_param", "limit"))
        params = urllib.parse.urlencode({query_param: query, limit_param: max(1, limit)})
        return f"{self._base_url}{endpoint}?{params}"

    def search(self, query: str, limit: int = 10, **kwargs: Any) -> List[RetrievedChunk]:
        url = self._build_request_url(query, limit)
        if not url:
            return []

        cfg = load_yaml(self._config_path)
        defaults = cfg.get("defaults", {})
        client_cfg = cfg.get("clients", {}).get(self._client_id, {})
        timeout = float(client_cfg.get("timeout_seconds", defaults.get("timeout_seconds", 6)))
        headers = dict(defaults.get("headers", {}))
        headers.update(client_cfg.get("headers", {}))
        if self._api_key:
            headers["Authorization"] = f"Bearer {self._api_key}"
        req = urllib.request.Request(url=url, headers=headers, method="GET")

        try:
            with urllib.request.urlopen(req, timeout=timeout) as res:
                payload = json.loads(res.read().decode("utf-8"))
        except Exception:
            return []

        docs = payload.get("documents", []) if isinstance(payload, dict) else []
        out: List[RetrievedChunk] = []
        for d in docs[:limit]:
            out.append(
                RetrievedChunk(
                    id=str(d.get("id", "")),
                    text=f"{d.get('title', '')}\n{d.get('content', '')}".strip(),
                    source=d.get("url", d.get("source", "api://source")),
                    score=float(d.get("score", 0.5)),
                    metadata={"connector": "api", "title": d.get("title", "")},
                )
            )
        return out
