from __future__ import annotations

from pathlib import Path
from typing import Dict

import yaml

from packages.core.domain.interfaces import PromptPolicy


class YamlPromptPolicyEngine(PromptPolicy):
    def __init__(self, policy_path: str) -> None:
        self._policy_path = Path(policy_path)
        self._cache: Dict[str, Dict] = {}

    def _load(self) -> Dict:
        if not self._cache:
            with self._policy_path.open("r", encoding="utf-8") as f:
                self._cache = yaml.safe_load(f) or {}
        return self._cache

    def build_system_prompt(self, client_id: str, mode: str) -> str:
        cfg = self._load()
        clients = cfg.get("clients", {})
        defaults = cfg.get("defaults", {})
        client_cfg = clients.get(client_id, {})

        base_prompt = client_cfg.get("base_system_prompt", defaults.get("base_system_prompt", ""))
        mode_overrides = client_cfg.get("mode_overrides", {})
        mode_prompt = mode_overrides.get(mode, "")
        rules = "\n".join(client_cfg.get("rules", defaults.get("rules", [])))
        escalation = client_cfg.get("escalation", defaults.get("escalation", ""))

        parts = [base_prompt, mode_prompt, rules, escalation]
        return "\n\n".join(p.strip() for p in parts if p and p.strip())
