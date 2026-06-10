# POAMSKP production migration & deploy runbook

Step-by-step checklist to deploy the Simasia chatbot platform for **POAMSKP** on GCP.

| Item | Value |
|------|-------|
| Tenant `client_id` | `default` (POAMSKP data lives under `data/clients/default/`) |
| Region | `europe-west1` |
| GCS bucket | `simasia-chatbot-prod-${PROJECT_ID}` |
| Stack profile | `firebase` + `FIRESTORE_CONTROL_PLANE=true` |
| POAMSKP site | `https://www.poamskp.gr` / `https://poamskp.gr` |

Run all commands from a machine with `gcloud` authenticated and write access to the target project.  
Repo root for local commands: `chatbot_template/`.

> **Shell:** Commands below use bash syntax (`export`, `printf`, heredocs). On Windows, use **Git Bash**, **WSL**, or **Google Cloud Shell** — or see [PowerShell notes](#powershell-notes) at the end.

---

## 0. Pre-flight checklist

- [ ] POAMSKP tenant data is current locally (`data/clients/default/`: config, uploads, drive_cache, indexes).
- [ ] `data/clients/default/config/drive_sources.yaml` has the correct Drive folder ID.
- [ ] `data/clients/default/config/faq.json` includes `faq-poamskp-contact`.
- [ ] Eval suite has passed locally (`python -m apps.worker.cli job eval --client-id default`).
- [ ] You have Gemini API key(s), a strong admin token, and a freshly generated widget-key HMAC secret.
- [ ] **Do not** commit secrets, `.env`, or service-account JSON.

---

## 1. GCP project prerequisites

1. Create or select a GCP project with billing enabled.
2. Install and authenticate the CLI:

```bash
gcloud auth login
gcloud auth application-default login
export PROJECT_ID=your-gcp-project-id
gcloud config set project ${PROJECT_ID}
```

3. Note the project number (needed for default service accounts):

```bash
gcloud projects describe ${PROJECT_ID} --format='value(projectNumber)'
```

4. Enable required APIs:

```bash
gcloud services enable \
  run.googleapis.com \
  cloudbuild.googleapis.com \
  artifactregistry.googleapis.com \
  containerregistry.googleapis.com \
  storage.googleapis.com \
  firestore.googleapis.com \
  secretmanager.googleapis.com \
  iam.googleapis.com \
  iamcredentials.googleapis.com
```

Drive sync uses the Drive API via a **service-account JSON** (shared to the folder). No extra GCP API is strictly required beyond credentials with Drive scope, but enable if you use Google Workspace audit tooling:

```bash
gcloud services enable drive.googleapis.com
```

---

## 2. GCS bucket (europe-west1)

```bash
export REGION=europe-west1
export BUCKET=simasia-chatbot-prod-${PROJECT_ID}

gcloud storage buckets create gs://${BUCKET} \
  --project=${PROJECT_ID} \
  --location=${REGION} \
  --uniform-bucket-level-access
```

Verify:

```bash
gcloud storage buckets describe gs://${BUCKET} --format='value(location)'
```

Bucket layout after migration:

```
gs://${BUCKET}/clients/default/...     # tenant blobs (config, uploads, indexes, drive_cache)
gs://${BUCKET}/platform/registry.yaml  # staging fallback only — not used when Firestore CP is on
```

---

## 3. Firestore database + indexes

Create a Firestore **Native** database in `europe-west1` (skip if already exists):

```bash
gcloud firestore databases create \
  --project=${PROJECT_ID} \
  --location=${REGION} \
  --type=firestore-native
```

Create the widget-key lookup index (required for HMAC prefix auth):

```bash
gcloud firestore indexes composite create \
  --project=${PROJECT_ID} \
  --collection-group=widget_keys \
  --field-config field-path=key_prefix,order=ascending \
  --field-config field-path=status,order=ascending
```

Or deploy `deploy/firestore.indexes.json` via Firebase CLI (`queryScope: COLLECTION_GROUP` matches `collection_group("widget_keys")` in code).

Wait until the index shows **READY** in the console before rotating keys or serving traffic.

Collections used (Phase 20a):

| Collection | Purpose |
|------------|---------|
| `clients/{client_id}` | Registry metadata, config revision |
| `clients/{client_id}/widget_keys/{key_id}` | HMAC hash + prefix only |
| `clients/{client_id}/config_meta/{config_key}` | Config blob metadata (content in GCS) |
| `clients/{client_id}/jobs/{job_id}` | Job lifecycle (90-day TTL) |
| `admin_users/{uid}` | Scaffold only (unused until Firebase Auth) |

---

## 4. Secret Manager secrets

Generate values locally (never commit):

```bash
# Admin token (long random string)
python -c "import secrets; print(secrets.token_urlsafe(48))"

# Widget key HMAC secret (32+ bytes hex)
python -c "import secrets; print(secrets.token_hex(32))"
```

Create secrets:

```bash
# Gemini — single key
printf '%s' 'YOUR_GEMINI_API_KEY' | gcloud secrets create chatbot-gemini-api-key \
  --project=${PROJECT_ID} --data-file=-

# Optional: comma-separated key pool (maps to GEMINI_API_KEYS env var)
printf '%s' 'key1,key2,key3' | gcloud secrets create chatbot-gemini-api-keys \
  --project=${PROJECT_ID} --data-file=-

# Admin API token
printf '%s' 'YOUR_ADMIN_TOKEN' | gcloud secrets create chatbot-admin-api-token \
  --project=${PROJECT_ID} --data-file=-

# Widget key HMAC secret (required for Firestore control plane)
printf '%s' 'YOUR_WIDGET_KEY_HASH_SECRET_HEX' | gcloud secrets create chatbot-widget-key-hash-secret \
  --project=${PROJECT_ID} --data-file=-

# Google Drive service account JSON (full JSON body, one line or multiline)
gcloud secrets create chatbot-drive-credentials \
  --project=${PROJECT_ID} --data-file=path/to/drive-service-account.json
```

| Secret name | Env var | Required |
|-------------|---------|----------|
| `chatbot-gemini-api-key` | `GEMINI_API_KEY` | Yes |
| `chatbot-gemini-api-keys` | `GEMINI_API_KEYS` | Optional (key pool) |
| `chatbot-admin-api-token` | `ADMIN_API_TOKEN` | Yes |
| `chatbot-widget-key-hash-secret` | `WIDGET_KEY_HASH_SECRET` | Yes |
| `chatbot-drive-credentials` | `GOOGLE_DRIVE_CREDENTIALS_JSON` | Yes for Drive sync |

**Share the Drive folder** (`1-khDHT3FfegMUv1ssKXUl4CnK_GGmSOh` per current `drive_sources.yaml`) with the service account email (`....@....iam.gserviceaccount.com`) as **Viewer**.

---

## 5. Service accounts & IAM

### 5a. Dedicated service accounts (recommended)

```bash
gcloud iam service-accounts create chatbot-api \
  --project=${PROJECT_ID} \
  --display-name="Chatbot Cloud Run API"

gcloud iam service-accounts create chatbot-worker \
  --project=${PROJECT_ID} \
  --display-name="Chatbot Cloud Run Jobs worker"

export API_SA=chatbot-api@${PROJECT_ID}.iam.gserviceaccount.com
export WORKER_SA=chatbot-worker@${PROJECT_ID}.iam.gserviceaccount.com
```

### 5b. Grant roles

**API service account:**

```bash
for ROLE in \
  roles/secretmanager.secretAccessor \
  roles/datastore.user \
  roles/storage.objectAdmin \
  roles/run.developer; do
  gcloud projects add-iam-policy-binding ${PROJECT_ID} \
    --member="serviceAccount:${API_SA}" \
    --role="${ROLE}"
done
```

`roles/run.developer` lets the API trigger and poll Cloud Run Jobs via the Jobs API (Phase 21A). Do **not** set `CLOUD_RUN_JOBS_USE_GCLOUD=true` on the API.

**Worker service account:**

```bash
for ROLE in \
  roles/secretmanager.secretAccessor \
  roles/datastore.user \
  roles/storage.objectAdmin; do
  gcloud projects add-iam-policy-binding ${PROJECT_ID} \
    --member="serviceAccount:${WORKER_SA}" \
    --role="${ROLE}"
done
```

**Bucket-scoped alternative** (least privilege on GCS):

```bash
gcloud storage buckets add-iam-policy-binding gs://${BUCKET} \
  --member="serviceAccount:${API_SA}" \
  --role=roles/storage.objectAdmin

gcloud storage buckets add-iam-policy-binding gs://${BUCKET} \
  --member="serviceAccount:${WORKER_SA}" \
  --role=roles/storage.objectAdmin
```

### 5c. Cloud Build (image push)

Ensure Cloud Build can push images and deploy:

```bash
PROJECT_NUMBER=$(gcloud projects describe ${PROJECT_ID} --format='value(projectNumber)')
CB_SA="${PROJECT_NUMBER}@cloudbuild.gserviceaccount.com"

gcloud projects add-iam-policy-binding ${PROJECT_ID} \
  --member="serviceAccount:${CB_SA}" \
  --role=roles/run.admin
gcloud projects add-iam-policy-binding ${PROJECT_ID} \
  --member="serviceAccount:${CB_SA}" \
  --role=roles/iam.serviceAccountUser
gcloud projects add-iam-policy-binding ${PROJECT_ID} \
  --member="serviceAccount:${CB_SA}" \
  --role=roles/artifactregistry.writer
gcloud projects add-iam-policy-binding ${PROJECT_ID} \
  --member="serviceAccount:${CB_SA}" \
  --role=roles/storage.admin
```

(`storage.admin` covers legacy `gcr.io` pushes; use `artifactregistry.writer` if you migrate to Artifact Registry.)

---

## 6. Build & push API image

```bash
cd chatbot_template

gcloud builds submit \
  --project=${PROJECT_ID} \
  --tag gcr.io/${PROJECT_ID}/chatbot-api:latest \
  --dockerfile=deploy/Dockerfile.api .
```

---

## 7. Build & push worker image

```bash
gcloud builds submit \
  --project=${PROJECT_ID} \
  --tag gcr.io/${PROJECT_ID}/chatbot-worker:latest \
  --dockerfile=deploy/Dockerfile.worker \
  --build-arg GIT_SHA=$(git rev-parse --short HEAD) .
```

Ingest logs must include `[ingest-prep]` and `[drive-ingest]` lines (stdout). If missing, the job is running an old worker image.

---

## 8. Deploy Cloud Run API

First deploy with jobs disabled (safer for initial migration/smoke).  
Replace `API_URL` after deploy.

```bash
gcloud run deploy chatbot-api \
  --project=${PROJECT_ID} \
  --region=${REGION} \
  --image=gcr.io/${PROJECT_ID}/chatbot-api:latest \
  --service-account=${API_SA} \
  --allow-unauthenticated \
  --memory=2Gi \
  --cpu=2 \
  --timeout=300 \
  --min-instances=0 \
  --max-instances=10 \
  --set-env-vars="STACK_PROFILE=firebase,\
GOOGLE_CLOUD_PROJECT=${PROJECT_ID},\
GCS_BUCKET=${BUCKET},\
CLOUD_RUN_REGION=${REGION},\
FIRESTORE_CONTROL_PLANE=true,\
GCS_REGISTRY_FALLBACK=false,\
ALLOW_INSECURE_CLIENT_ID=false,\
ALLOW_INSECURE_ADMIN=false,\
CLOUD_RUN_JOBS_DISABLED=true,\
CLOUD_RUN_JOBS_USE_GCLOUD=false,\
CLOUD_RUN_JOB_PREFIX=chatbot,\
TENANT_CACHE_ROOT=/tmp/simasia-tenant-cache" \
  --set-secrets="GEMINI_API_KEY=chatbot-gemini-api-key:latest,\
ADMIN_API_TOKEN=chatbot-admin-api-token:latest,\
WIDGET_KEY_HASH_SECRET=chatbot-widget-key-hash-secret:latest,\
GOOGLE_DRIVE_CREDENTIALS_JSON=chatbot-drive-credentials:latest"
```

Optional: add `GEMINI_API_KEYS=chatbot-gemini-api-keys:latest` to `--set-secrets` if using a key pool.

Capture URL:

```bash
export API_URL=$(gcloud run services describe chatbot-api \
  --project=${PROJECT_ID} --region=${REGION} \
  --format='value(status.url)')
echo ${API_URL}
```

---

## 9. Configure Cloud Run Jobs

Create one job per job type. Worker entrypoint: `python -m apps.worker.cli job <type> --client-id default`.

Shared env for all jobs:

```bash
JOB_ENV="STACK_PROFILE=firebase,GOOGLE_CLOUD_PROJECT=${PROJECT_ID},GCS_BUCKET=${BUCKET},FIRESTORE_CONTROL_PLANE=true,GCS_REGISTRY_FALLBACK=false,CLOUD_RUN_REGION=${REGION},TENANT_CACHE_ROOT=/tmp/simasia-tenant-cache,ALLOW_INSECURE_CLIENT_ID=false,ALLOW_INSECURE_ADMIN=false"
JOB_SECRETS="GEMINI_API_KEY=chatbot-gemini-api-key:latest,ADMIN_API_TOKEN=chatbot-admin-api-token:latest,WIDGET_KEY_HASH_SECRET=chatbot-widget-key-hash-secret:latest,GOOGLE_DRIVE_CREDENTIALS_JSON=chatbot-drive-credentials:latest"
```

Worker jobs call `build_stack()` and require `ADMIN_API_TOKEN` for firebase security validation (same as API).

Create jobs:

```bash
# Ingest
gcloud run jobs create chatbot-ingest \
  --project=${PROJECT_ID} --region=${REGION} \
  --image=gcr.io/${PROJECT_ID}/chatbot-worker:latest \
  --service-account=${WORKER_SA} \
  --memory=4Gi --cpu=2 --task-timeout=3600 \
  --set-env-vars="${JOB_ENV}" \
  --set-secrets="${JOB_SECRETS}" \
  --command=python,-m,apps.worker.cli,job,ingest,--client-id,default

# Eval
gcloud run jobs create chatbot-eval \
  --project=${PROJECT_ID} --region=${REGION} \
  --image=gcr.io/${PROJECT_ID}/chatbot-worker:latest \
  --service-account=${WORKER_SA} \
  --memory=4Gi --cpu=2 --task-timeout=3600 \
  --set-env-vars="${JOB_ENV}" \
  --set-secrets="${JOB_SECRETS}" \
  --command=python,-m,apps.worker.cli,job,eval,--client-id,default,--suite,full,--llm-mode,live

# Drive sync
gcloud run jobs create chatbot-drive-sync \
  --project=${PROJECT_ID} --region=${REGION} \
  --image=gcr.io/${PROJECT_ID}/chatbot-worker:latest \
  --service-account=${WORKER_SA} \
  --memory=2Gi --cpu=1 --task-timeout=1800 \
  --set-env-vars="${JOB_ENV}" \
  --set-secrets="${JOB_SECRETS}" \
  --command=python,-m,apps.worker.cli,job,drive-sync,--client-id,default

# Crawl (Playwright — needs worker image)
gcloud run jobs create chatbot-crawl \
  --project=${PROJECT_ID} --region=${REGION} \
  --image=gcr.io/${PROJECT_ID}/chatbot-worker:latest \
  --service-account=${WORKER_SA} \
  --memory=4Gi --cpu=2 --task-timeout=3600 \
  --set-env-vars="${JOB_ENV}" \
  --set-secrets="${JOB_SECRETS}" \
  --command=python,-m,apps.worker.cli,job,crawl,--client-id,default

# Deploy (activate index — short job)
gcloud run jobs create chatbot-deploy \
  --project=${PROJECT_ID} --region=${REGION} \
  --image=gcr.io/${PROJECT_ID}/chatbot-worker:latest \
  --service-account=${WORKER_SA} \
  --memory=1Gi --cpu=1 --task-timeout=600 \
  --set-env-vars="${JOB_ENV}" \
  --set-secrets="${JOB_SECRETS}" \
  --command=python,-m,apps.worker.cli,job,deploy,--client-id,default
```

Manual job execution (recommended until a Cloud Run Jobs API client replaces shell dispatch):

```bash
gcloud run jobs execute chatbot-ingest --project=${PROJECT_ID} --region=${REGION} --wait
```

**Job dispatch from the API:** The API image does **not** include the `gcloud` CLI. Do **not** set `CLOUD_RUN_JOBS_USE_GCLOUD=true` — it will fail if admin routes try to shell out to `gcloud`.

Production recommendation:

- `CLOUD_RUN_JOBS_DISABLED=true` — admin job routes run in-process on the API container (OK for short jobs; ingest/eval may hit the 300s API timeout).
- `CLOUD_RUN_JOBS_USE_GCLOUD=false` — always, until a proper Jobs API trigger is implemented.
- Run long jobs via `gcloud run jobs execute …` from your workstation or Cloud Shell.

Optional: set `CLOUD_RUN_JOBS_DISABLED=false` only if you accept in-process execution on API for admin-triggered jobs (still keep `USE_GCLOUD=false`).

Admin dashboard routes: `POST /v1/admin/clients/default/jobs/*` (in-process when jobs not disabled).

---

## 10. Migrate local tenant data → GCS

From `chatbot_template/` with ADC (`gcloud auth application-default login`):

```bash
export GOOGLE_CLOUD_PROJECT=${PROJECT_ID}
export GCS_BUCKET=${BUCKET}

# Dry-run (default — omit --apply)
python -m apps.worker.jobs.migrate_to_gcs --client-id default

# Apply (uploads data/clients/default/** and platform/registry.yaml)
python -m apps.worker.jobs.migrate_to_gcs --client-id default --apply
```

Paths resolve from repo root (`data/clients`, `packages/config/clients/registry.yaml`) regardless of shell CWD.

**Canonical GCS layout:** `gs://${BUCKET}/clients/default/...` (matches `migrate_to_gcs`). Runtime reads legacy `gs://${BUCKET}/default/...` only as fallback when canonical objects are missing. Do **not** manually mirror `clients/default/indexes` into `default/indexes`; no rsync is required. On firebase startup, **config** files are hydrated into `${TENANT_CACHE_ROOT}/default/config/` before the API loads tenant config. **Ingest jobs** hydrate `config/*`, **drive cache** (`drive_cache/drive_sync_manifest.json` plus indexable files under `drive_cache/files/`), and active index state from GCS before indexing. **Eval jobs** persist `tests/output/latest_eval_report.json` and the referenced run directory to GCS after a pass. **Deploy jobs** hydrate that latest pointer plus the referenced run dir (not historical output), along with `tests/eval_suite.yaml`, `tests/cases/**`, optional `tests/fixtures/**`, and **index state** (`indexes/active_manifest.json` plus blobs under `indexes/versions/<pending|active|previous>/`) from an empty `/tmp` cache. On successful deploy, activation writes `clients/{client_id}/indexes/active_manifest.json` back to GCS (not only `/tmp`).

Verify object count:

```bash
gcloud storage ls -r gs://${BUCKET}/clients/default/ | head
gcloud storage ls gs://${BUCKET}/platform/
```

---

## 10b. Admin pipeline run (Phase 21A — preferred for normal operations)

After the API is deployed with Firestore control plane, use the **admin pipeline API** or the React admin dashboard **Pipeline automation** panel instead of running each Cloud Run job manually.

**Presets:**

| Preset | Steps |
|--------|--------|
| `sync_only` | drive-sync |
| `ingest_eval` | ingest → eval |
| `full_deploy` | drive-sync → ingest → eval → deploy |

**API (admin token required):**

```bash
export API_URL=https://simasia-chatbot-api-....run.app
export ADMIN_TOKEN=...

# Full pipeline for client default
curl -s -X POST "${API_URL}/v1/admin/clients/default/pipeline/run" \
  -H "x-admin-token: ${ADMIN_TOKEN}" \
  -H "Content-Type: application/json" \
  -d '{"preset":"full_deploy","eval_llm_mode":"live"}'

# Poll status
curl -s "${API_URL}/v1/admin/clients/default/pipeline/status/PIPELINE_ID" \
  -H "x-admin-token: ${ADMIN_TOKEN}"

# List recent runs
curl -s "${API_URL}/v1/admin/clients/default/pipeline/runs" \
  -H "x-admin-token: ${ADMIN_TOKEN}"
```

**Safety:** Deploy runs only when eval `status=pass` and `deploy_eligible=true`. Empty ingest (`chunks_total=0`) blocks deploy unless `force_empty_deploy=true`.

**After deploy:** Restart the Cloud Run API service (or redeploy) so runtime index hydration loads the new active version. The pipeline response includes `runtime_refresh_note` when deploy succeeds.

**Cloud Run dispatch:** The API uses the Cloud Run Jobs API (ADC) — not `gcloud` in the container. Set `CLOUD_RUN_JOBS_DISABLED=false` on the API service when worker jobs should execute remotely. The pipeline orchestrator polls execution status and hydrates GCS results into `/tmp` before the next step. Manual `gcloud run jobs execute` remains a fallback.

**Async contract:** `POST /pipeline/run` returns **HTTP 202** with `pipeline_id` and `status=pending` immediately. Orchestration runs in a background thread; poll `GET /pipeline/status/{pipeline_id}`. Do **not** set `ADMIN_JOBS_SYNC` on the API service.

**Smoke checklist:** [POAMSKP-phase21a-smoke.md](./POAMSKP-phase21a-smoke.md)

**Phase 21A client_id:** Container arg overrides pass `--client-id {client_id}` to worker CLI. POAMSKP uses `default`; multi-tenant dynamic jobs are Phase 21B.

---

## 11. Migrate registry → Firestore (hashed keys only)

Dry-run (no Firestore write):

```bash
export WIDGET_KEY_HASH_SECRET=YOUR_WIDGET_KEY_HASH_SECRET_HEX

python -m apps.worker.jobs.migrate_registry_to_firestore \
  --source packages/config/clients/registry.yaml
```

To migrate from the GCS copy instead, download it first (`load_yaml` is local-path only):

```bash
gcloud storage cp gs://${BUCKET}/platform/registry.yaml /tmp/registry.yaml

python -m apps.worker.jobs.migrate_registry_to_firestore \
  --source /tmp/registry.yaml
```

Apply (requires `WIDGET_KEY_HASH_SECRET` + Firestore access):

```bash
export WIDGET_KEY_HASH_SECRET=YOUR_WIDGET_KEY_HASH_SECRET_HEX
export GOOGLE_CLOUD_PROJECT=${PROJECT_ID}

python -m apps.worker.jobs.migrate_registry_to_firestore \
  --source packages/config/clients/registry.yaml \
  --apply
```

**Security:** migration stores **HMAC hashes only**. Migrated staging keys are for testing — **not** for production traffic.

---

## 12. Migrate config metadata → Firestore

Reads local `data/clients/default/config/*` and writes Firestore metadata (blobs must already be in GCS from step 10):

```bash
export GOOGLE_CLOUD_PROJECT=${PROJECT_ID}
export WIDGET_KEY_HASH_SECRET=YOUR_WIDGET_KEY_HASH_SECRET_HEX

python -m apps.worker.jobs.migrate_config_meta_to_firestore \
  --client-id default --clients-root data/clients

python -m apps.worker.jobs.migrate_config_meta_to_firestore \
  --client-id default --clients-root data/clients --apply
```

---

## 13. Rotate widget key (required before prod)

Generate a **fresh** production key with POAMSKP allowed origins.  
Save the returned `widget_key` exactly once — it is never shown again.

```bash
export ADMIN_TOKEN=YOUR_ADMIN_TOKEN

curl -sS -X POST "${API_URL}/v1/admin/clients/default/widget-keys/rotate" \
  -H "Content-Type: application/json" \
  -H "x-admin-token: ${ADMIN_TOKEN}" \
  -d '{
    "allowed_origins": [
      "https://www.poamskp.gr",
      "https://poamskp.gr"
    ],
    "revoke_key_id": "default_widget_1"
  }' | jq .
```

Verify list shows prefix only (no full key):

```bash
curl -sS "${API_URL}/v1/admin/clients/default/widget-keys" \
  -H "x-admin-token: ${ADMIN_TOKEN}" | jq .
```

Store the new key in your password manager. Configure the POAMSKP site / widget embed:

```
x-client-key: wk_...   # header on chat requests
```

For the React widget dev harness:

```bash
cd frontends/react-widget
# .env.local
VITE_CHATBOT_API_BASE=${API_URL}
VITE_CLIENT_ID=default
VITE_CLIENT_KEY=wk_<paste once>
VITE_CHAT_API_VERSION=v2
npm run dev
```

---

## 14. Drive folder setup & sync

### 14a. Confirm drive source config

Current POAMSKP source (in GCS after migration):

```yaml
# clients/default/config/drive_sources.yaml
sources:
  - id: poamskp_drive
    folder_id: 1-khDHT3FfegMUv1ssKXUl4CnK_GGmSOh
    title: POAMSKP Drive
    enabled: true
```

Add or update via admin API if needed:

```bash
curl -sS "${API_URL}/v1/admin/clients/default/drive-sources" \
  -H "x-admin-token: ${ADMIN_TOKEN}" | jq .

curl -sS -X POST "${API_URL}/v1/admin/clients/default/drive-sources" \
  -H "Content-Type: application/json" \
  -H "x-admin-token: ${ADMIN_TOKEN}" \
  -d '{
    "folder_id": "1-khDHT3FfegMUv1ssKXUl4CnK_GGmSOh",
    "title": "POAMSKP Drive",
    "enabled": true,
    "recursive": true,
    "max_files": 200
  }' | jq .
```

### 14b. Trigger Drive sync

Via admin API (runs in API container when `CLOUD_RUN_JOBS_DISABLED=true`):

```bash
curl -sS -X POST "${API_URL}/v1/admin/clients/default/jobs/drive-sync" \
  -H "Content-Type: application/json" \
  -H "x-admin-token: ${ADMIN_TOKEN}" \
  -d '{}' | jq .

# Poll job
export JOB_ID=job_xxxxxxxxxxxx
curl -sS "${API_URL}/v1/admin/clients/default/jobs/${JOB_ID}" \
  -H "x-admin-token: ${ADMIN_TOKEN}" | jq .
```

Or via Cloud Run Job:

```bash
gcloud run jobs execute chatbot-drive-sync \
  --project=${PROJECT_ID} --region=${REGION} --wait
```

Confirm credentials:

```bash
curl -sS "${API_URL}/v1/admin/clients/default/drive-sources" \
  -H "x-admin-token: ${ADMIN_TOKEN}" | jq '.credentials_configured, .service_account_email'
```

---

## 15. Ingest → eval → deploy

### 15a. Ingest

```bash
curl -sS -X POST "${API_URL}/v1/admin/clients/default/jobs/ingest" \
  -H "x-admin-token: ${ADMIN_TOKEN}" | jq .
```

Wait for `status: succeeded`, note `result.version_id`.

Or:

```bash
gcloud run jobs execute chatbot-ingest --project=${PROJECT_ID} --region=${REGION} --wait
```

### 15b. Eval

```bash
curl -sS -X POST "${API_URL}/v1/admin/clients/default/jobs/eval" \
  -H "Content-Type: application/json" \
  -H "x-admin-token: ${ADMIN_TOKEN}" \
  -d '{"suite": "full", "llm_mode": "live"}' | jq .
```

Check latest eval:

```bash
curl -sS "${API_URL}/v1/admin/clients/default/eval/latest" \
  -H "x-admin-token: ${ADMIN_TOKEN}" | jq '.status, .deploy_eligible'
```

Local smoke suite (**local dev only** — not wired to prod API/key unless you configure env):

```bash
cd chatbot_template
pytest tests/test_smoke_polish.py -q -k poamskp
```

### 15c. Deploy active index

Deploy is gated on eval — fails with 409 if eval not eligible.

```bash
curl -sS -X POST "${API_URL}/v1/admin/clients/default/deploy" \
  -H "Content-Type: application/json" \
  -H "x-admin-token: ${ADMIN_TOKEN}" \
  -d '{}' | jq .
```

Verify index:

```bash
curl -sS "${API_URL}/v1/admin/clients/default/index" \
  -H "x-admin-token: ${ADMIN_TOKEN}" | jq .
```

---

## 16. Smoke tests

Set variables:

```bash
export API_URL=https://chatbot-api-xxxxx-ew.a.run.app
export WIDGET_KEY=wk_<production key from rotation>
export ADMIN_TOKEN=...
```

### 16a. Health

```bash
curl -sS "${API_URL}/health" | jq .
# Expected: {"status":"ok"}
```

### 16b. Chat (v2)

```bash
curl -sS -X POST "${API_URL}/v2/chat/respond" \
  -H "Content-Type: application/json" \
  -H "x-client-key: ${WIDGET_KEY}" \
  -H "Origin: https://www.poamskp.gr" \
  -d '{
    "client_id": "default",
    "message": "Τι είναι το MYRTO;",
    "stream": false
  }' | jq '.answer'
```

Wrong key must fail:

```bash
curl -sS -o /dev/null -w "%{http_code}\n" -X POST "${API_URL}/v2/chat/respond" \
  -H "Content-Type: application/json" \
  -H "x-client-key: wk_invalid" \
  -d '{"client_id":"default","message":"test"}'
# Expected: 401
```

### 16c. POAMSKP contact question

```bash
curl -sS -X POST "${API_URL}/v2/chat/respond" \
  -H "Content-Type: application/json" \
  -H "x-client-key: ${WIDGET_KEY}" \
  -H "Origin: https://www.poamskp.gr" \
  -d '{
    "client_id": "default",
    "message": "Πώς μπορώ να επικοινωνήσω με την ΠΟΑμΣΚΠ;",
    "stream": false
  }' | jq '.answer'
```

Expect phone `213`, email/site `poamskp` in the answer (from FAQ + Drive corpus).

### 16d. Drive sync status

```bash
curl -sS "${API_URL}/v1/admin/clients/default/drive-sources" \
  -H "x-admin-token: ${ADMIN_TOKEN}" | jq '.sources[] | {id, status, files_synced, last_synced_at}'
```

Expect `poamskp_drive` status `synced` or `synced_with_warnings`.

### 16e. Admin dashboard

Run locally against production API:

```bash
cd frontends/react-widget
cat > .env.local <<EOF
VITE_CHATBOT_API_BASE=${API_URL}
VITE_ADMIN_API_BASE=${API_URL}
VITE_CLIENT_ID=default
VITE_CLIENT_KEY=${WIDGET_KEY}
VITE_CHAT_API_VERSION=v2
EOF
npm run dev
```

Open `http://localhost:5173` → **Admin** tab → enter admin token + client `default`.

Verify: client summary, index status, eval summary, drive sources panel, job triggers.

### 16f. POAMSKP website widget

Update the POAMSKP site embed to call `${API_URL}` with header `x-client-key` (replace Netlify Gemini proxy).  
Allowed origin must match the rotate step. Test from `https://www.poamskp.gr`.

---

## 17. Rollback

### 17a. Index rollback (preferred)

```bash
curl -sS -X POST "${API_URL}/v1/admin/clients/default/rollback" \
  -H "x-admin-token: ${ADMIN_TOKEN}" | jq .
```

### 17b. Registry fallback (one release only)

Emergency fallback to GCS `platform/registry.yaml` plaintext registry:

```bash
gcloud run services update chatbot-api \
  --project=${PROJECT_ID} --region=${REGION} \
  --update-env-vars="GCS_REGISTRY_FALLBACK=true,FIRESTORE_CONTROL_PLANE=false"
```

Revert as soon as possible — plaintext registry is not production-safe.

### 17c. Redeploy previous image

```bash
gcloud run services update chatbot-api \
  --project=${PROJECT_ID} --region=${REGION} \
  --image=gcr.io/${PROJECT_ID}/chatbot-api:PREVIOUS_TAG
```

### 17d. Widget key compromise

List keys and note the `key_id` to revoke:

```bash
curl -sS "${API_URL}/v1/admin/clients/default/widget-keys" \
  -H "x-admin-token: ${ADMIN_TOKEN}" | jq '.[] | {key_id, key_prefix, status}'
```

Revoke the compromised key (replace `KEY_ID_FROM_LIST`):

```bash
curl -sS -X POST "${API_URL}/v1/admin/clients/default/widget-keys/KEY_ID_FROM_LIST/revoke" \
  -H "x-admin-token: ${ADMIN_TOKEN}" -w "\n%{http_code}\n"
```

Rotate new key (section 13) and update POAMSKP site embed.

---

## 18. Known temporary limitations

| Limitation | Detail |
|------------|--------|
| Traces / metrics / sessions | Still **SQLite on Cloud Run filesystem** — ephemeral across redeploys/scale-to-zero. Phase **20b** moves these to Firestore. |
| Firebase Auth / `client_admin` | Not implemented. Admin access is **`x-admin-token` only**. |
| Scheduled jobs | No Cloud Scheduler wiring yet. Drive sync, ingest, eval are **manual** (admin UI, curl, or `gcloud run jobs execute`). |
| Job dispatch | API image has **no `gcloud` CLI** — keep `CLOUD_RUN_JOBS_USE_GCLOUD=false`. Run long jobs via `gcloud run jobs execute` from Cloud Shell/local. |
| `platform/registry.yaml` in GCS | Staging/rollback only when `GCS_REGISTRY_FALLBACK=true`. Production auth is Firestore HMAC keys. |
| Admin dashboard hosting | Not deployed to GCP in this runbook — run **locally** via Vite or host `frontends/react-widget` separately. |
| POAMSKP legacy chatbot | `POAMSKP/js/chatbot.js` still targets Netlify proxy until you repoint it to Cloud Run. |

---

## Quick reference — env vars (firebase production)

| Variable | Value |
|----------|-------|
| `STACK_PROFILE` | `firebase` |
| `GOOGLE_CLOUD_PROJECT` | your project |
| `GCS_BUCKET` | `simasia-chatbot-prod-${PROJECT_ID}` |
| `CLOUD_RUN_REGION` | `europe-west1` |
| `FIRESTORE_CONTROL_PLANE` | `true` |
| `GCS_REGISTRY_FALLBACK` | `false` |
| `ALLOW_INSECURE_CLIENT_ID` | `false` |
| `ALLOW_INSECURE_ADMIN` | `false` |
| `CLOUD_RUN_JOBS_DISABLED` | `true` initially (in-process admin jobs); long jobs via `gcloud run jobs execute` |
| `CLOUD_RUN_JOBS_USE_GCLOUD` | `false` (required — API cannot shell out to gcloud) |
| `CLOUD_RUN_JOB_PREFIX` | `chatbot` |
| `TENANT_CACHE_ROOT` | `/tmp/simasia-tenant-cache` |

Secrets via Secret Manager: `GEMINI_API_KEY`, `ADMIN_API_TOKEN`, `WIDGET_KEY_HASH_SECRET`, `GOOGLE_DRIVE_CREDENTIALS_JSON`, optional `GEMINI_API_KEYS`.

Worker Cloud Run Jobs need the same `ADMIN_API_TOKEN` and `WIDGET_KEY_HASH_SECRET` secrets as the API.

---

## PowerShell notes

Prefer **Git Bash**, **WSL**, or **Google Cloud Shell** for the bash blocks above. PowerShell equivalents for the first steps:

```powershell
$env:PROJECT_ID = "your-gcp-project-id"
$env:REGION = "europe-west1"
$env:BUCKET = "simasia-chatbot-prod-$($env:PROJECT_ID)"
gcloud config set project $env:PROJECT_ID

# Dry-run GCS migration (from chatbot_template/)
$env:GOOGLE_CLOUD_PROJECT = $env:PROJECT_ID
python -m apps.worker.jobs.migrate_to_gcs --client-id default

# Build API image
gcloud builds submit --project=$env:PROJECT_ID `
  --tag "gcr.io/$($env:PROJECT_ID)/chatbot-api:latest" `
  --dockerfile=deploy/Dockerfile.api .
```

Use `$env:TEMP\registry.yaml` instead of `/tmp/registry.yaml` when downloading registry from GCS.

---

## Related docs

- Generic deploy notes: [README-deploy.md](./README-deploy.md)
- Firestore index spec: [firestore.indexes.json](./firestore.indexes.json)
- API contract: [../docs/api-contract.md](../docs/api-contract.md)
