# Example configs (safe to commit)

Fake/demo data only. Copy patterns into `data/clients/<client_id>/config/` for real clients.

| Path | Purpose |
|------|---------|
| `demo_client/client.yaml` | Display name, language, suggested questions |
| `demo_client/source_whitelist.yaml` | Public domain allowlist |
| `demo_client/privacy.yaml` | Privacy mode defaults |

Widget registry: see `packages/config/clients/registry.example.yaml`.

Stack profiles (no secrets): `config/stacks/local.yaml`, `firebase.yaml`, `enterprise.yaml`.

Environment: copy `.env.example` to `.env` at repo root.
