# Modular Chatbot Template

This repository now contains a new modular chatbot platform designed for multi-client deployments.

Existing folders `POAMSKP` and `simasiaAI_website` are kept untouched for reference during migration.

## Goals

- Python backend with protected provider keys.
- Frontend-agnostic API (React, Vue, vanilla JS, mobile can all integrate).
- Swappable adapters for LLMs, retrieval, vector stores, and knowledge sources.
- Config-driven prompt policies and UI theming.
- Multi-source retrieval support (local files + Google Drive + API + DB together).

## New Structure

- `apps/api`: FastAPI application and HTTP routes.
- `apps/worker`: indexing and sync job entry points.
- `packages/core`: domain models, interfaces, orchestrator, policy engines.
- `packages/adapters`: concrete connector/retriever/provider/vector adapters.
- `packages/config`: schemas and default client/mode configs.
- `frontends/react-widget`: starter React widget using backend contracts.
- `docs`: architecture and API contract documentation.

## Quick Start (Local MVP)

For production client onboarding, see **PART B** in `docs/CHATBOT-RAG-BUILD-GUIDE.txt` (v2 per-client layout).

1. Create and activate a virtual environment.
2. Install dependencies: `pip install -r requirements.txt`
3. Copy `.env.example` to `.env` and set `GEMINI_API_KEY` and `ADMIN_API_TOKEN` (never commit `.env`).
4. Copy `packages/config/clients/registry.example.yaml` to `registry.yaml` and set widget keys.
5. Run: `uvicorn apps.api.main:app --reload --port 8000`

For the React widget, set `VITE_CLIENT_KEY` to a key from `registry.yaml` (must match `client_id` in requests).

## Google Drive Sync (local MVP only)

Legacy shared-default workflow — not production multi-tenant onboarding.

1. Set `GOOGLE_DRIVE_CREDENTIALS_JSON` in `.env` to your service-account JSON path.
2. Configure Drive folder IDs in `packages/config/defaults/drive_sources.yaml`.
3. Run source sync:
   - `python -m apps.worker.jobs.sync_sources`
4. This writes indexed chunks to `packages/config/defaults/google_drive_index.json`.
5. Runtime `google_drive` connector reads that index for retrieval.

Production uses `data/clients/<client_id>/` and per-client ingest (PART D Phase 3).

## DB Connector (SQLite default)

1. Optionally set `DB_SQLITE_PATH` in `.env` (defaults to `packages/config/defaults/chatbot.sqlite3`).
2. Seed DB chunks from local and Drive index:
   - `python -m apps.worker.jobs.build_index`
3. Runtime `db` connector will query table `knowledge_chunks` and join federated retrieval results.

## Vector Mode (`vector_db`)

- `build_index` now also creates `packages/config/defaults/vector_index.json`.
- Vector retrieval is enabled by setting request `mode` to `vector_db`.
- Vector index build uses Gemini embeddings when `GEMINI_API_KEY` is available (`EMBEDDING_MODEL` configurable).
- If Gemini embedding is unavailable, it automatically falls back to deterministic embeddings for local development.
- If `QDRANT_URL` is configured, index build also upserts vectors to Qdrant and `vector_db` runtime uses Qdrant retrieval.

## API Connector

- Configure `API_CONNECTOR_BASE_URL` and optional `API_CONNECTOR_API_KEY`.
- Enable per client in `packages/config/defaults/api_sources.yaml`.
- Expected response shape from source API:
  - `{ "documents": [{ "id": "...", "title": "...", "content": "...", "url": "...", "score": 0.7 }] }`

## Admin Config Endpoints

- Protected via `ADMIN_API_TOKEN` (header: `x-admin-token`) → `platform_admin`.
- `GET/PUT /v1/admin/prompt-policy`
- `GET/PUT /v1/admin/themes`
- `GET/PUT /v1/admin/clients`
- `GET/PUT /v1/admin/sources/drive`
- `GET/PUT /v1/admin/sources/api`
- Runtime reload is automatic after prompt/theme/client/api updates.

## API

- `POST /v1/chat/respond` — requires `x-client-key` (or `ALLOW_INSECURE_CLIENT_ID=true` for local dev)
- `GET /v1/theme/{client_id}` — requires `x-client-key`; path must match resolved tenant
- `GET /v1/config/public/{client_id}`

## Per-client config (Phase 2)

Runtime prompt/theme/config loads from:

```
packages/domain_packs/<pack_id>/     ← base templates (generic only in repo)
data/clients/<client_id>/config/   ← client overrides (client.yaml required)
```

Merge order: **domain pack → client overrides** (client wins). Override files are optional; pack supplies defaults.

Required on disk: `client.yaml`. Required after merge: `prompt_policy.base_system_prompt`, `themes.colors`, `client.display_name`.

Initialize a new client:

```bash
python -m apps.worker.jobs.init_client --client-id acme --domain-pack generic
```

## Tests

```bash
python -m pytest tests/ -v
```

See `docs/CHATBOT-RAG-BUILD-GUIDE.txt` — **PART D** (authoritative). Stack profiles: §D30, `config/stacks/`.

See `docs/architecture.md` and `docs/api-contract.md` for summaries and API shapes.

## Environment Variables

Set these in `.env`:

- `GEMINI_API_KEY`: Gemini key for generation and embedding.
- `STACK_PROFILE`: `local` (default, no Firebase) | `firebase` (production MVP) | `enterprise` (not implemented).
- `DEFAULT_CLIENT_ID`: default client profile id (usually `default`).
- `DEFAULT_MODEL`: Gemini generation model (default `gemini-2.5-flash-lite`).
- `EMBEDDING_MODEL`: Gemini embedding model (default `gemini-embedding-001`).
- `GOOGLE_DRIVE_CREDENTIALS_JSON`: path to service account JSON (root-relative recommended, e.g. `service-account.json`).
- `DB_SQLITE_PATH`: optional SQLite path (if empty, defaults to `packages/config/defaults/chatbot.sqlite3`).
- `API_CONNECTOR_BASE_URL`: optional external API source base URL.
- `API_CONNECTOR_API_KEY`: optional bearer token for API source.
- `QDRANT_URL`: optional Qdrant URL. If empty, local vector index file is used.
- `QDRANT_API_KEY`: optional key for secured/cloud Qdrant.
- `QDRANT_COLLECTION`: Qdrant collection name (default `chatbot_chunks`).
- `ADMIN_API_TOKEN`: required for `/v1/admin/*` endpoints (Phase 1).
- `ALLOW_INSECURE_ADMIN`: `true` for local dev only when `ADMIN_API_TOKEN` is unset (never in production/firebase).
- `CLIENT_REGISTRY_PATH`: widget key registry YAML (default `packages/config/clients/registry.yaml`).
- `ALLOW_INSECURE_CLIENT_ID`: `true` for local dev without widget key (never in production).

## YAML Configuration Files

- `packages/config/defaults/clients.yaml`
  - runtime modes and source weights per client.
  - controls which modes appear in public config and weighting in federated retrieval.
- `packages/config/defaults/prompt_policy.yaml`
  - system prompt, rules, mode overrides, escalation behavior per client.
- `packages/config/defaults/themes.yaml`
  - UI token values (colors/radius/assets) with client overrides.
- `packages/config/defaults/drive_sources.yaml`
  - Drive sync behavior (`chunk_size`, `overlap`, mime types, roots per client).
- `packages/config/defaults/api_sources.yaml`
  - API connector behavior (`enabled`, endpoint path, params, timeout, headers).

## Presets (What To Fill)

### 1) Local Demo (fastest)

- Fill:
  - `GEMINI_API_KEY`
- Optional:
  - `ADMIN_API_TOKEN`
- Leave empty:
  - `GOOGLE_DRIVE_CREDENTIALS_JSON`, `API_CONNECTOR_*`, `QDRANT_*`

### 2) Local + Google Drive

- Fill:
  - `GEMINI_API_KEY`
  - `GOOGLE_DRIVE_CREDENTIALS_JSON=service-account.json`
- Configure:
  - Drive folder roots in `drive_sources.yaml`
- Run:
  - `python -m apps.worker.jobs.sync_sources`
  - `python -m apps.worker.jobs.build_index`

### 3) Local + External API source

- Fill:
  - `GEMINI_API_KEY`
  - `API_CONNECTOR_BASE_URL`
  - `API_CONNECTOR_API_KEY` (if required)
- Configure:
  - set `clients.default.enabled: true` in `api_sources.yaml`

### 4) Production-like Vector (Qdrant)

- Fill:
  - `GEMINI_API_KEY`
  - `QDRANT_URL`
  - `QDRANT_API_KEY` (if required)
  - `QDRANT_COLLECTION` (optional custom name)
- Run:
  - `python -m apps.worker.jobs.build_index`
  - this also upserts vectors to Qdrant when configured.
