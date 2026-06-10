# Phase 19 — manual Cloud Run deploy (europe-west1)



> **POAMSKP production**

> - Full runbook: [POAMSKP-production-runbook.md](./POAMSKP-production-runbook.md)

> - Printable checklist: [POAMSKP-production-checklist.md](./POAMSKP-production-checklist.md)

> - Env template: [poamskp.env.production.example](./poamskp.env.production.example)



> **Shell:** Use Git Bash, WSL, or Google Cloud Shell for bash commands below.



## Prerequisites



- GCP project with billing enabled

- `gcloud` CLI authenticated

- Private GCS bucket: `simasia-chatbot-prod-{PROJECT_ID}` (uniform access, no public access)

- Secret Manager secrets (never commit values):

  - `chatbot-gemini-api-key` → `GEMINI_API_KEY`

  - `chatbot-admin-api-token` → `ADMIN_API_TOKEN`

  - `chatbot-widget-key-hash-secret` → `WIDGET_KEY_HASH_SECRET`

  - `chatbot-drive-credentials` → `GOOGLE_DRIVE_CREDENTIALS_JSON` (optional)



Enable APIs (include container registry for `gcr.io` pushes):



```bash

gcloud services enable run.googleapis.com cloudbuild.googleapis.com \

  artifactregistry.googleapis.com containerregistry.googleapis.com \

  storage.googleapis.com firestore.googleapis.com secretmanager.googleapis.com

```



## 1. Create bucket (private)



```bash

export PROJECT_ID=your-project-id

export REGION=europe-west1

export BUCKET=simasia-chatbot-prod-${PROJECT_ID}



gcloud storage buckets create gs://${BUCKET} \

  --project=${PROJECT_ID} \

  --location=${REGION} \

  --uniform-bucket-level-access

```



## 2. Migrate local tenant data (dry-run first)



```bash

cd chatbot_template

export GOOGLE_CLOUD_PROJECT=${PROJECT_ID}

python -m apps.worker.jobs.migrate_to_gcs --client-id default

python -m apps.worker.jobs.migrate_to_gcs --client-id default --apply

```



Dry-run is the default (omit `--apply`). Paths resolve from repo root.



Uploads `clients/{client_id}/...` (canonical GCS layout via `gcs_object_name`) and `platform/registry.yaml`.

**GCS layout (canonical):** `gs://BUCKET/clients/{client_id}/...`  
Legacy `gs://BUCKET/{client_id}/...` is read at runtime for backward compatibility.  
Runtime hydrates `config/*` on API startup; eval and deploy gate hydrate `tests/eval_suite.yaml`, `tests/cases/**`, optional `tests/fixtures/**`, plus `indexes/active_manifest.json` and pending/active/previous version blobs under `indexes/versions/**`. Eval jobs persist `tests/output/latest_eval_report.json` and the referenced run directory to GCS; deploy jobs hydrate only that latest pointer and run dir (not historical output).

**Phase 21A admin pipeline:** `POST /v1/admin/clients/{client_id}/pipeline/run` with presets `sync_only`, `ingest_eval`, or `full_deploy` chains drive-sync → ingest → eval → deploy. Status is stored in Firestore (`clients/{id}/pipelines/{pipeline_id}`). Cloud Run job dispatch uses the Jobs API (ADC), not `gcloud` in the API container. Manual `gcloud run jobs execute` remains a fallback.



**Note:** Plaintext widget keys in `platform/registry.yaml` are **staging-only** until Phase 20 hashed storage.



## 3. Build & push API image



```bash

gcloud builds submit --tag gcr.io/${PROJECT_ID}/chatbot-api:latest \

  --dockerfile=deploy/Dockerfile.api .

```



## 4. Deploy Cloud Run service



```bash

gcloud run deploy chatbot-api \

  --image gcr.io/${PROJECT_ID}/chatbot-api:latest \

  --region ${REGION} \

  --project ${PROJECT_ID} \

  --set-env-vars STACK_PROFILE=firebase,GOOGLE_CLOUD_PROJECT=${PROJECT_ID},GCS_BUCKET=${BUCKET},CLOUD_RUN_REGION=${REGION},FIRESTORE_CONTROL_PLANE=true,GCS_REGISTRY_FALLBACK=false,ALLOW_INSECURE_CLIENT_ID=false,ALLOW_INSECURE_ADMIN=false,CLOUD_RUN_JOBS_DISABLED=true,CLOUD_RUN_JOBS_USE_GCLOUD=false \

  --set-secrets GEMINI_API_KEY=chatbot-gemini-api-key:latest,ADMIN_API_TOKEN=chatbot-admin-api-token:latest,WIDGET_KEY_HASH_SECRET=chatbot-widget-key-hash-secret:latest \

  --memory 2Gi --cpu 2 --timeout 300 --min-instances 0

```



### Ephemeral SQLite (Phase 19 MVP)



Traces, sessions, and metrics use SQLite on the container filesystem. **Data may be lost on redeploy or scale-to-zero.** Phase 20b replaces this with Firestore.



### FAISS index cache



Active indexes download to `/tmp/simasia-tenant-cache` (override with `TENANT_CACHE_ROOT`). Cached by `version_id` to avoid re-download when unchanged.



## 5. Cloud Run Jobs (optional Phase 19)



Build worker image:



```bash

gcloud builds submit --tag gcr.io/${PROJECT_ID}/chatbot-worker:latest \

  --dockerfile=deploy/Dockerfile.worker .

```



Example job (worker requires `ADMIN_API_TOKEN` for firebase stack validation):



```bash

gcloud run jobs create chatbot-ingest \

  --image gcr.io/${PROJECT_ID}/chatbot-worker:latest \

  --region ${REGION} \

  --command python,-m,apps.worker.cli,job,ingest,--client-id,default \

  --set-env-vars STACK_PROFILE=firebase,GOOGLE_CLOUD_PROJECT=${PROJECT_ID},GCS_BUCKET=${BUCKET},FIRESTORE_CONTROL_PLANE=true \

  --set-secrets GEMINI_API_KEY=chatbot-gemini-api-key:latest,ADMIN_API_TOKEN=chatbot-admin-api-token:latest,WIDGET_KEY_HASH_SECRET=chatbot-widget-key-hash-secret:latest

```



Run jobs manually (API image has no `gcloud` CLI — do **not** set `CLOUD_RUN_JOBS_USE_GCLOUD=true`):



```bash

gcloud run jobs execute chatbot-ingest --region ${REGION} --wait

```



## 6. Local dev unchanged



```bash

STACK_PROFILE=local

uvicorn apps.api.main:app --reload --port 8000

```



## 7. Firestore control plane (Phase 20a)



Create Firestore database in **europe-west1** (default DB is fine).



Required Secret Manager secret:



- `chatbot-widget-key-hash-secret` → `WIDGET_KEY_HASH_SECRET`



Deploy env additions:



```bash

FIRESTORE_CONTROL_PLANE=true

WIDGET_KEY_HASH_SECRET=<from Secret Manager>

GCS_REGISTRY_FALLBACK=false

CLOUD_RUN_JOBS_USE_GCLOUD=false

```



Create composite index (Firestore console or `deploy/firestore.indexes.json` — `COLLECTION_GROUP` scope):



```bash

gcloud firestore indexes composite create \

  --collection-group=widget_keys \

  --field-config field-path=key_prefix,order=ascending \

  --field-config field-path=status,order=ascending

```



Migrate registry (dry-run first):



```bash

python -m apps.worker.jobs.migrate_registry_to_firestore --source packages/config/clients/registry.yaml

gcloud storage cp gs://BUCKET/platform/registry.yaml /tmp/registry.yaml

python -m apps.worker.jobs.migrate_registry_to_firestore --source /tmp/registry.yaml --apply

```



Migrate config metadata:



```bash

python -m apps.worker.jobs.migrate_config_meta_to_firestore --client-id default

python -m apps.worker.jobs.migrate_config_meta_to_firestore --client-id default --apply

```



**POAMSKP production:** after migration, rotate widget keys before real prod traffic:



```bash

curl -X POST .../v1/admin/clients/default/widget-keys/rotate -H "x-admin-token: ..."

```



Plaintext widget keys in Firestore are forbidden. `platform/registry.yaml` is staging-only; use `GCS_REGISTRY_FALLBACK=true` only for one-release rollback.



Phase 20b (traces/metrics/sessions) is deferred — SQLite on Cloud Run remains ephemeral until then.

