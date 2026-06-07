from __future__ import annotations

from packages.core.config.loader import TenantConfigLoader
from packages.core.domain.interfaces import PromptPolicy


class TenantPromptPolicyEngine(PromptPolicy):
    def __init__(self, config_loader: TenantConfigLoader) -> None:
        self._loader = config_loader

    def build_system_prompt(self, client_id: str, mode: str) -> str:
        cfg = self._loader.load(client_id).prompt_policy
        base_prompt = cfg.get("base_system_prompt", "")
        mode_prompt = (cfg.get("mode_overrides") or {}).get(mode, "")
        rules_list = cfg.get("rules") or []
        rules = "\n".join(f"- {r}" if not str(r).strip().startswith("-") else str(r) for r in rules_list)
        escalation = cfg.get("escalation", "")
        parts = [base_prompt, mode_prompt, rules, escalation]
        citation_rules = cfg.get("citation_rules", "")
        if citation_rules:
            parts.append(citation_rules)
        return "\n\n".join(p.strip() for p in parts if p and str(p).strip())
