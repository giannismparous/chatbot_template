from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from packages.config.loaders import load_yaml
from packages.core.config.merger import deep_merge
from packages.core.config.models import ConfigValidationError, MergedTenantConfig, validate_merged_config
from packages.core.llm.validation import validate_llm_config
from packages.core.privacy.config import validate_privacy_config
from packages.core.safety.config import validate_safety_config
from packages.core.tenant.paths import client_config_dir, domain_pack_dir, safe_client_id

CONFIG_FILES = {
    "client": "client.yaml",
    "prompt_policy": "prompt_policy.yaml",
    "themes": "themes.yaml",
    "locale": "locale.yaml",
    "privacy": "privacy.yaml",
    "source_whitelist": "source_whitelist.yaml",
    "domain_pack": "domain_pack.yaml",
    "ingestion": "ingestion.yaml",
    "retrieval_rules": "retrieval_rules.yaml",
    "guardrails": "guardrails.yaml",
    "crisis_rules": "crisis_rules.yaml",
    "disclaimers": "disclaimers.yaml",
    "escalation_rules": "escalation_rules.yaml",
    "llm": "llm.yaml",
}

FAQ_FILENAME = "faq.json"

REQUIRED_CLIENT_FILES = ("client.yaml",)


class TenantConfigLoader:
    """Load merged tenant config: domain pack base + client overrides."""

    def __init__(
        self,
        clients_root: Path,
        domain_packs_root: Path,
        *,
        default_domain_pack: str = "generic",
    ) -> None:
        self._clients_root = clients_root.resolve()
        self._domain_packs_root = domain_packs_root.resolve()
        self._default_domain_pack = default_domain_pack
        self._cache: dict[str, MergedTenantConfig] = {}

    def clear_cache(self, client_id: str | None = None) -> None:
        if client_id is None:
            self._cache.clear()
            return
        self._cache.pop(safe_client_id(client_id), None)

    def get_client_config_dir(self, client_id: str) -> Path:
        return client_config_dir(self._clients_root, client_id)

    def get_domain_pack_dir(self, pack_id: str) -> Path:
        return domain_pack_dir(self._domain_packs_root, pack_id)

    def _sanitize_pack_id(self, raw: str | None) -> str:
        if not raw or not str(raw).strip():
            return self._default_domain_pack
        try:
            return safe_client_id(str(raw).strip())
        except ValueError as exc:
            raise ConfigValidationError(str(exc)) from exc

    def _resolve_domain_pack_id(self, client_id: str, client_cfg: dict[str, Any]) -> str:
        domain_pack_file = self._load_yaml_file(
            self.get_client_config_dir(client_id) / CONFIG_FILES["domain_pack"]
        )
        raw = (
            client_cfg.get("domain_pack")
            or domain_pack_file.get("pack_id")
            or domain_pack_file.get("domain_pack")
            or self._default_domain_pack
        )
        return self._sanitize_pack_id(str(raw) if raw is not None else None)

    def _load_yaml_file(self, path: Path) -> dict[str, Any]:
        if not path.is_file():
            return {}
        data = load_yaml(str(path))
        return data if isinstance(data, dict) else {}

    def _load_json_file(self, path: Path) -> dict[str, Any]:
        if not path.is_file():
            return {}
        data = json.loads(path.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}

    def _merge_json_file(self, pack_dir: Path, client_dir: Path, filename: str) -> dict[str, Any]:
        base = self._load_json_file(pack_dir / filename)
        override = self._load_json_file(client_dir / filename)
        if not base and not override:
            return {}
        return deep_merge(base, override)

    def _merge_file(self, pack_dir: Path, client_dir: Path, filename: str) -> dict[str, Any]:
        base = self._load_yaml_file(pack_dir / filename)
        override = self._load_yaml_file(client_dir / filename)
        if not base and not override:
            return {}
        return deep_merge(base, override)

    def load(self, client_id: str, *, validate: bool = True) -> MergedTenantConfig:
        try:
            cid = safe_client_id(client_id)
        except ValueError as exc:
            raise ConfigValidationError(str(exc)) from exc
        if cid in self._cache:
            return self._cache[cid]

        client_dir = self.get_client_config_dir(cid)
        if not client_dir.is_dir():
            raise ConfigValidationError(f"Client config directory not found: {client_dir}")

        for required in REQUIRED_CLIENT_FILES:
            if not (client_dir / required).is_file():
                raise ConfigValidationError(
                    f"Client {cid!r} missing required file: {required}"
                )

        client_override = self._load_yaml_file(client_dir / CONFIG_FILES["client"])
        pack_id = self._resolve_domain_pack_id(cid, client_override)
        try:
            pack_dir = self.get_domain_pack_dir(pack_id)
        except ValueError as exc:
            raise ConfigValidationError(str(exc)) from exc
        if not pack_dir.is_dir():
            raise ConfigValidationError(f"Domain pack not found: {pack_id!r}")

        merged_client = deep_merge(
            self._load_yaml_file(pack_dir / CONFIG_FILES["client"]),
            client_override,
        )
        merged_client.setdefault("client_id", cid)
        merged_client.setdefault("domain_pack", pack_id)

        merged = MergedTenantConfig(
            client_id=cid,
            domain_pack=pack_id,
            client=merged_client,
            prompt_policy=self._merge_file(
                pack_dir, client_dir, CONFIG_FILES["prompt_policy"]
            ),
            themes=self._merge_file(pack_dir, client_dir, CONFIG_FILES["themes"]),
            locale=self._merge_file(pack_dir, client_dir, CONFIG_FILES["locale"]),
            privacy=self._merge_file(pack_dir, client_dir, CONFIG_FILES["privacy"]),
            source_whitelist=self._merge_file(
                pack_dir, client_dir, CONFIG_FILES["source_whitelist"]
            ),
            ingestion=self._merge_file(pack_dir, client_dir, CONFIG_FILES["ingestion"]),
            retrieval_rules=self._merge_file(
                pack_dir, client_dir, CONFIG_FILES["retrieval_rules"]
            ),
            faq=self._merge_json_file(pack_dir, client_dir, FAQ_FILENAME),
            guardrails=self._merge_file(pack_dir, client_dir, CONFIG_FILES["guardrails"]),
            crisis_rules=self._merge_file(pack_dir, client_dir, CONFIG_FILES["crisis_rules"]),
            disclaimers=self._merge_file(pack_dir, client_dir, CONFIG_FILES["disclaimers"]),
            escalation_rules=self._merge_file(
                pack_dir, client_dir, CONFIG_FILES["escalation_rules"]
            ),
            llm=self._merge_file(pack_dir, client_dir, CONFIG_FILES["llm"]),
        )

        if validate:
            validate_merged_config(merged)
            validate_safety_config(merged)
            validate_llm_config(merged)
            validate_privacy_config(merged)

        self._cache[cid] = merged
        return merged
