from __future__ import annotations

import argparse
from pathlib import Path

from packages.config.loaders import save_yaml
from packages.core.stack.factory import project_root
from packages.core.tenant.paths import client_config_dir, client_root, safe_client_id


def _client_yaml_template(client_id: str, domain_pack: str, display_name: str) -> dict:
    return {
        "client_id": client_id,
        "display_name": display_name,
        "domain_pack": domain_pack,
    }


def init_client(
    client_id: str,
    *,
    domain_pack: str = "generic",
    display_name: str | None = None,
    clients_root: Path | None = None,
) -> Path:
    cid = safe_client_id(client_id)
    pack_id = safe_client_id(domain_pack)
    root = clients_root or (project_root() / "data" / "clients")
    tenant_root = client_root(root, cid)
    config_dir = client_config_dir(root, cid)
    config_dir.mkdir(parents=True, exist_ok=True)

    for sub in ("uploads", "indexes", "logs", "tests", "web_cache", "drive_cache"):
        (tenant_root / sub).mkdir(parents=True, exist_ok=True)
    (tenant_root / "indexes" / "versions").mkdir(parents=True, exist_ok=True)
    (tenant_root / "tests" / "cases").mkdir(parents=True, exist_ok=True)

    _seed_eval_templates(config_dir, cid)

    client_yaml_path = config_dir / "client.yaml"
    if client_yaml_path.exists():
        raise FileExistsError(f"Client already exists: {client_yaml_path}")

    save_yaml(
        str(client_yaml_path),
        _client_yaml_template(
            cid,
            pack_id,
            display_name or cid.replace("_", " ").title(),
        ),
    )
    return config_dir


def _seed_eval_templates(config_dir: Path, client_id: str) -> None:
    root = project_root()
    pack = root / "packages" / "domain_packs" / "generic"
    tests_dir = config_dir.parent / "tests"
    suite_tpl = pack / "eval_suite.template.yaml"
    cases_tpl = pack / "eval_cases.template.yaml"
    if suite_tpl.is_file():
        text = suite_tpl.read_text(encoding="utf-8").replace("{{client_id}}", client_id)
        (tests_dir / "eval_suite.yaml").write_text(text, encoding="utf-8")
    if cases_tpl.is_file():
        (tests_dir / "cases" / "starter.yaml").write_text(
            cases_tpl.read_text(encoding="utf-8"),
            encoding="utf-8",
        )
    mapping_tpl = pack / "source_mapping.template.yaml"
    if mapping_tpl.is_file():
        (config_dir / "source_mapping.yaml").write_text(
            mapping_tpl.read_text(encoding="utf-8"),
            encoding="utf-8",
        )
    web_tpl = pack / "web_sources.template.yaml"
    if web_tpl.is_file():
        (config_dir / "web_sources.yaml").write_text(
            web_tpl.read_text(encoding="utf-8"),
            encoding="utf-8",
        )
    drive_tpl = pack / "drive_sources.template.yaml"
    if drive_tpl.is_file():
        (config_dir / "drive_sources.yaml").write_text(
            drive_tpl.read_text(encoding="utf-8"),
            encoding="utf-8",
        )


def main() -> None:
    parser = argparse.ArgumentParser(description="Initialize a new client config skeleton.")
    parser.add_argument("--client-id", required=True, help="Tenant client_id")
    parser.add_argument("--domain-pack", default="generic", help="Domain pack id (default: generic)")
    parser.add_argument("--display-name", default=None, help="Human-readable client name")
    parser.add_argument(
        "--clients-root",
        default=None,
        help="Override clients root (default: data/clients)",
    )
    args = parser.parse_args()
    clients_root = Path(args.clients_root) if args.clients_root else None
    path = init_client(
        args.client_id,
        domain_pack=args.domain_pack,
        display_name=args.display_name,
        clients_root=clients_root,
    )
    print(f"Created client config at {path}")
    print("Optional overrides: prompt_policy.yaml, themes.yaml, locale.yaml, privacy.yaml, ...")


if __name__ == "__main__":
    main()
