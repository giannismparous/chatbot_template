# Architecture

**Authoritative design:** `docs/CHATBOT-RAG-BUILD-GUIDE.txt` — **PART D only**

PART C is historical context (superseded). PART A is reference benchmark. PART B is operational guide (v2 per-client layout).

## Platform positioning

Configurable platform for Greek-first, regulated-domain, citation-guaranteed chatbots. We do **not** train custom LLMs. Quality comes from offline indexing, hybrid retrieval, rules, prompts, deterministic safety layers, evals, and compliance tooling. LLM providers remain swappable (Gemini default).

Core platform is **generic**. Domain/client behavior lives in **client config** + **domain packs** — never hardcoded org names, acronyms, crisis hotlines, or healthcare/Greek-government logic in core code.

Infrastructure is **adapter-based**. Business logic never imports Firebase, Firestore, GCS, or Qdrant directly. Active backends are selected by `STACK_PROFILE` (see §D30).

---

## System overview

```
┌──────────────────────────────────────────────────────────────────────────┐
│  Frontends — widget / client site / mobile                               │
│  Auth: x-client-key + origin binding (client_id NOT trusted from body)    │
└───────────────────────────────┬──────────────────────────────────────────┘
                                │
┌───────────────────────────────▼──────────────────────────────────────────┐
│  API (FastAPI) + ChatOrchestrator (vendor-agnostic core)                 │
└───────────────────────────────┬──────────────────────────────────────────┘
                                │
         Provider interfaces (ConfigStore, AuthProvider, VectorStore, …)
```

---

## Implementation stack profiles (D30)

| Profile | Env | Status | Meaning |
|---------|-----|--------|---------|
| **local/dev** | `STACK_PROFILE=local` | **Implement first** | Phase 1 must work; no Firebase/GCP |
| **firebase/gcp** | `STACK_PROFILE=firebase` | **Default prod target** | Stack YAML + factory now; GCP adapters Phase 11+ progressively |
| **enterprise** | `STACK_PROFILE=enterprise` | **Documented only** | Future; factory rejects until built |

Config: `config/stacks/local.yaml`, `firebase.yaml`, `enterprise.yaml` (no secrets)

### Phase 1 auth (all profiles)

- **Widget:** `x-client-key` → `client_id`, origin binding, body mismatch → 403 (YAML registry now; Firestore registry Phase 11)
- **Admin MVP:** `x-admin-token` → `platform_admin` only
- **Firebase Admin Auth** → Phase 11

### Provider ports (minimal in Phase 1)

Phase 1 defines only: `AuthProvider`, `AdminAuthProvider`, `ConfigStore`. Other ports added when their feature phase requires them.

| Interface | local/dev | firebase/gcp adapters |
|-----------|-----------|------------------------|
| AuthProvider | Phase 1 ✓ | Registry → Firestore Phase 11 |
| AdminAuthProvider | Phase 1 token | Firebase Auth Phase 11 |
| ConfigStore | Phase 1–2 YAML | Firestore Phase 11 |
| FileStore | local Phase 19 ✓ | GcsFileStore Phase 19 ✓ |

**Firestore:** control plane only — not primary vector retrieval.

---

## Key flows (summary)

| Flow | Summary |
|------|---------|
| **Request** | Auth → crisis filter → retrieve → LLM → post-process citations |
| **Admin** | platform_admin (full) vs client_admin (safe self-service) — D29 |
| **Privacy** | Redaction before trace write — Phase 8 before Phase 9 |
| **Eval** | Deploy blocked until tests pass |

---

## Implementation status

| Area | Status |
|------|--------|
| Basic orchestrator + connectors | MVP done (shared defaults) |
| Stack profiles + minimal ports | Phase 1 scaffolds local only |
| local/dev adapters | Phase 1 (widget auth + YAML config) |
| firebase/gcp adapters | Phase 11+ (progressive) |
| enterprise stack | Documented only |

**First code phase:** Phase 1 — tenant isolation, widget auth, minimal ports, local stack factory.

See `docs/CHATBOT-RAG-BUILD-GUIDE.txt` PART D §D23–D30.

---

## Documentation map

| Document | Contents |
|----------|----------|
| `CHATBOT-RAG-BUILD-GUIDE.txt` | PART D authoritative design |
| `api-contract.md` | HTTP shapes, auth, admin RBAC |
| `architecture.md` | This file |
| `config/stacks/*.yaml` | Stack profile selection (no secrets) |
| `.env.example` | Safe env template |
| `packages/config/clients/registry.example.yaml` | Fake widget keys only |
