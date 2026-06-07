# API Contract

Target design: **PART D** in `docs/CHATBOT-RAG-BUILD-GUIDE.txt` (PART C superseded). Current code implements a subset.

---

## Authentication

| Tier | Header | Role | Use |
|------|--------|------|-----|
| Widget | `x-client-key: <widget_public_key>` | — | Embedded chat; maps 1:1 to `client_id` |
| Integration | `Authorization: Bearer <integration_secret>` | scoped | Server-to-server; optional `debug` scope |
| Admin | `Authorization: Bearer <admin_jwt>` | `platform_admin` \| `client_admin` | Admin console |
| Admin (MVP dev) | `x-admin-token` | `platform_admin` only | Local dev/staging |

- Backend resolves `client_id` from credentials — **not from body alone**
- Body `client_id` must match resolved id or → `403`
- `client_admin` JWT MUST include `client_id` claim; requests to other clients → `403`
- Widget keys may bind `allowed_origins`
- MVP dev: `ALLOW_INSECURE_CLIENT_ID=true` (local only)

### Admin roles (see PART D §D29)

| Role | Scope |
|------|--------|
| `platform_admin` | All tenants; all admin endpoints |
| `client_admin` | Single `client_id`; safe self-service subset only |

Optional scopes (future): `debug:traces` (time-limited full trace for client_admin), `deploy:request`.

---

## POST `/v1/chat/respond`

### Request headers

```
Content-Type: application/json
x-client-key: <widget_public_key>
```

### Request body

```json
{
  "client_id": "acme",
  "session_id": "sess_abc123",
  "user_id": "optional-opaque-id",
  "message": "Ποια είναι τα ωράρια λειτουργίας;",
  "history": [
    { "role": "user", "content": "Γεια σας" },
    { "role": "assistant", "content": "..." }
  ],
  "language": "el",
  "mode": "hybrid_local",
  "top_k": 6,
  "stream": false,
  "debug": false
}
```

| Field | Required | Notes |
|-------|----------|-------|
| `session_id` | Recommended | Follow-up rewrite, multi-turn context |
| `user_id` | Optional | Hashed in logs per privacy mode |
| `language` | Optional | `"el"` \| `"en"`; auto-detect if omitted |
| `stream` | Optional | `true` → SSE |
| `debug` | Optional | Returns `trace_id` only — **never full trace** |

### Response (non-streaming)

```json
{
  "answer": "Τα ωράρια είναι Δευτέρα–Παρασκευή 09:00–18:00 [1].",
  "sources": [
    {
      "index": 1,
      "title": "Ωράρια εξυπηρέτησης",
      "url": "https://acme.gr/contact",
      "clickable": true
    }
  ],
  "confidence": {
    "level": "high",
    "reason": "FAQ hit plus supporting document [1]."
  },
  "requires_human": false,
  "escalation": null,
  "trace_id": "tr_7f3a9c2e",
  "session_id": "sess_abc123"
}
```

**Citation rules (response):**
- `answer` contains inline `[1]`, `[2]` — only indices present in `sources`
- **Regulated mode:** citations must be sentence/claim-level; end-of-paragraph-only citations fail validation
- Every factual claim must have valid `[n]` or be rephrased as "not found in approved sources"
- `citation_enforcer` validates every `[n]` maps to a retrieved chunk
- Post-processor strips invented citation markers and LLM-invented URLs
- `sources` built from retrieved chunks + `source_whitelist.yaml`; **public URLs only** when `show_public_sources_only: true`
- `confidence.level`: `"high"` \| `"medium"` \| `"low"` — never a fake decimal
- `requires_human`: `true` when escalation rules fire (regulated domains)

**Debug (widget):**
- `debug: true` adds/returns `trace_id` only
- Response MUST NOT include retrieved chunks, scores, prompts, rejected chunks, or internal URLs

### Streaming (SSE)

```
event: chunk
data: {"text": "Τα ωράρια είναι "}

event: done
data: {
  "answer": "Τα ωράρια είναι Δευτέρα–Παρασκευή 09:00–18:00 [1].",
  "sources": [...],
  "confidence": { "level": "high", "reason": "..." },
  "requires_human": false,
  "trace_id": "tr_7f3a9c2e",
  "session_id": "sess_abc123"
}
```

### Special responses (no LLM or post-gate)

| Condition | Behavior |
|-----------|----------|
| `crisis_filter` hit | Guaranteed safety message from `crisis_rules.yaml`; `requires_human` may be true |
| Grounding gate (empty/weak) | "Not found in approved sources" + optional `escalation.suggest_contact` |
| Provider blocked | Safe canned message; no raw provider error |
| Input blocked | Refusal without LLM call |

---

## GET `/v1/admin/traces/{trace_id}`

**platform_admin** or integration credential with `debug` scope. **client_admin** forbidden unless explicit `debug:traces` scope granted.

Full internal trace (fields may be absent/redacted per `privacy.yaml`):

- original message (if `store_raw_messages`), rewritten query, FAQ hits
- retrieved chunks with scores, boosts/penalties
- selected vs rejected chunks with reasons
- model, latency breakdown, token usage
- citation validation result (including claim-level pass/fail in regulated mode)
- crisis/blocked events

`do_not_log` / `aggregate_only` modes: raw query/answer not stored.

---

## GET `/v1/theme/{client_id}`

Branding + optional frontend flags: `streaming`, `stt_enabled`, `tts_enabled`, `citation_rendering`.

---

## GET `/v1/config/public/{client_id}`

Modes, languages, suggested questions, regulated_mode flag (informational).

---

## Admin — client lifecycle

Permission key: **P** = platform_admin only, **C** = client_admin (own client), **⚡** = approval-gated.

| Method | Path | P | C | Purpose |
|--------|------|---|---|---------|
| `POST` | `/v1/admin/clients` | ✓ | ✗ | Create client + widget key + domain pack |
| `GET/PUT` | `/v1/admin/clients/{id}/faq` | ✓ | ✓ | FAQ / contact / business info |
| `GET/PUT` | `/v1/admin/clients/{id}/prompt-policy` | ✓ | ✓* | Prompts (*business overlay only for C) |
| `GET/PUT` | `/v1/admin/clients/{id}/retrieval-rules` | ✓ | ✗ | Boosts, fusion weights |
| `GET/PUT` | `/v1/admin/clients/{id}/crisis-rules` | ✓ | ✗ | Crisis categories + hotlines |
| `GET/PUT` | `/v1/admin/clients/{id}/sources` | ✓ | ✓ | Websites, Drive, ingest settings |
| `POST` | `/v1/admin/clients/{id}/sources/{sid}/approve` | ✓ | ✗ | Approve pending domain (⚡) |
| `GET/PUT` | `/v1/admin/clients/{id}/source-whitelist` | ✓ | ✗ | Public domains, URL rules |
| `GET/PUT` | `/v1/admin/clients/{id}/guardrails` | ✓ | ✗ | Jailbreak, off-topic |
| `GET/PUT` | `/v1/admin/clients/{id}/privacy` | ✓ | ✗ | Logging mode, retention |
| `GET/PUT` | `/v1/admin/clients/{id}/compliance` | ✓ | ✗ | Artifact metadata |
| `GET/PUT` | `/v1/admin/clients/{id}/llm` | ✓ | ✗ | Model chain, temperature |
| `GET/PUT` | `/v1/admin/clients/{id}/themes` | ✓ | ✓ | Branding + suggested questions |
| `POST` | `/v1/admin/clients/{id}/uploads` | ✓ | ✓ | File upload |
| `POST` | `/v1/admin/clients/{id}/reindex` | ✓ | ✓ | Queue offline ingest (no auto-deploy) |
| `POST` | `/v1/admin/clients/{id}/preview` | ✓ | ✓** | Preview answer |
| `POST` | `/v1/admin/clients/{id}/run-tests` | ✓ | ✓ | Automated test suite (read results) |
| `POST` | `/v1/admin/clients/{id}/run-reviewer-eval` | ✓ | ✗ | Export reviewer CSV/Excel |
| `POST` | `/v1/admin/clients/{id}/deploy` | ✓ | ⚡ | Activate index (C: policy/regulated gate) |
| `POST` | `/v1/admin/clients/{id}/rollback-index` | ✓ | ✗ | Revert to previous index |
| `GET` | `/v1/admin/clients/{id}/metrics` | ✓ | ✓ | Allowed analytics dashboard |
| `GET` | `/v1/admin/clients/{id}/conversations` | ✓ | ✓*** | Conversation logs per privacy mode |
| `GET` | `/v1/admin/traces/{trace_id}` | ✓ | ✗**** | Full debug trace |

\* client_admin may edit greeting/tone/business fields only; `security_rules[]` and system prompt core are platform-only.

\*\* client_admin preview: answer + confidence + public sources + summary; no full trace.

\*\*\* absent or redacted per `privacy.yaml` (`do_not_log`, `aggregate_only`).

\*\*\*\* unless explicit `debug:traces` scope granted by platform_admin.

Regulated mode: code blocks client_admin from whitelist, safety, privacy, deploy bypass, and internal source exposure regardless of UI.

### Deploy gate

`POST .../deploy` requires:
- `test_report.status == "pass"` (retrieval, jailbreak, off-topic, citation tests)
- If `regulated_mode`: reviewer sign-off flag + `compliance.profile_complete` + claim-level citation tests pass

---

## source_whitelist.yaml (config shape)

```yaml
allowed_public_domains:
  - acme.gr
  - www.acme.gr
allowed_internal_sources:
  - drive:fileId123
  - upload:handbook.pdf
citation_url_rules:
  prefer_public_url: true
  strip_llm_urls: true
  allow_only_whitelisted: true
show_public_sources_only: true
```

---

## Legacy MVP endpoints (migration)

- `GET/PUT /v1/admin/prompt-policy` (global — migrate to per-client)
- `GET/PUT /v1/admin/themes`, `/v1/admin/clients`, `/v1/admin/sources/drive`, `/v1/admin/sources/api`

---

## Implementation status

| Feature | Status |
|---------|--------|
| Basic chat | Implemented |
| `x-client-key`, sessions, streaming | Designed |
| Claim-level citation `[n]` + enforcer | Designed |
| `source_whitelist.yaml` | Designed |
| `confidence.level` + reason | Designed |
| Crisis response path | Designed |
| Privacy-before-trace | Designed |
| Admin trace endpoint (platform_admin) | Designed |
| Stack profiles + provider ports | Designed — Phase 1 scaffolds |
| Admin RBAC (platform_admin / client_admin) | Designed — Phase 1 scaffolds auth; Phase 11 enforces |
| Reviewer eval export | Designed |
| Deploy gate | Designed |

See `docs/CHATBOT-RAG-BUILD-GUIDE.txt` PART D §D7, D27, D28, **D29**.
