# POAMSKP Phase 21A — production smoke checklist

Use after deploying API + worker images that include Phase 21A pipeline automation.

**One-command smoke (recommended):**

```bash
export ADMIN_TOKEN="$(gcloud secrets versions access latest --secret=chatbot-admin-api-token --project=simasia-ai-chatbot-production)"
export WIDGET_KEY='wk_...'   # optional, for chat smoke
export OLD_PIPELINES='pipe_2fea8723ca1c'   # optional stale cleanup
bash deploy/phase21a_prod_smoke.sh
```

The script builds images, updates all jobs (including `chatbot-pipeline`), deploys API, runs `ingest_eval` + `full_deploy` smoke, and prints PASS/FAIL.

**Project:** `simasia-ai-chatbot-production`  
**Region:** `europe-west1`  
**Client:** `default`  
**API SA:** `chatbot-api@simasia-ai-chatbot-production.iam.gserviceaccount.com`

---

## 0. Preconditions

- [ ] API image rebuilt with Phase 21A code
- [ ] Worker image rebuilt with latest ingest/eval/deploy fixes (same tag used for all jobs)
- [ ] `CLOUD_RUN_JOBS_DISABLED=false` on API service
- [ ] `CLOUD_RUN_JOBS_USE_GCLOUD=false` on API service
- [ ] `ADMIN_JOBS_SYNC` **not** set on API (must be unset/false)
- [ ] Firestore control plane enabled (`FIRESTORE_CONTROL_PLANE=true`)
- [ ] API SA has `roles/run.developer`, `roles/datastore.user`, `roles/storage.objectAdmin`, `roles/secretmanager.secretAccessor`
- [ ] `chatbot-pipeline` Cloud Run job exists and uses latest worker image
- [ ] Worker SA can run child jobs (`chatbot-drive-sync`, `chatbot-ingest`, `chatbot-eval`, `chatbot-deploy`) and write Firestore/GCS

---

## 1. Deploy API (Cloud Shell)

```bash
export PROJECT_ID=simasia-ai-chatbot-production
export REGION=europe-west1
export BUCKET=simasia-chatbot-prod-simasia-ai-chatbot-production
export API_IMAGE=gcr.io/${PROJECT_ID}/simasia-chatbot-api:phase21a

cd ~/chatbot_template   # repo root

gcloud builds submit --project=${PROJECT_ID} \
  --tag ${API_IMAGE} \
  --dockerfile=deploy/Dockerfile.api .

gcloud run deploy simasia-chatbot-api \
  --project=${PROJECT_ID} \
  --region=${REGION} \
  --image=${API_IMAGE} \
  --service-account=chatbot-api@${PROJECT_ID}.iam.gserviceaccount.com \
  --update-env-vars=STACK_PROFILE=firebase,GOOGLE_CLOUD_PROJECT=${PROJECT_ID},GCS_BUCKET=${BUCKET},CLOUD_RUN_REGION=${REGION},FIRESTORE_CONTROL_PLANE=true,GCS_REGISTRY_FALLBACK=false,CLOUD_RUN_JOBS_DISABLED=false,CLOUD_RUN_JOBS_USE_GCLOUD=false,CLOUD_RUN_JOB_PREFIX=chatbot,DEFAULT_CLIENT_ID=default \
  --update-secrets=GEMINI_API_KEY=chatbot-gemini-api-key:latest,ADMIN_API_TOKEN=chatbot-admin-api-token:latest,WIDGET_KEY_HASH_SECRET=chatbot-widget-key-hash-secret:latest,GOOGLE_DRIVE_CREDENTIALS_JSON=chatbot-drive-credentials:latest \
  --memory=2Gi --cpu=2 --timeout=300 --min-instances=0
```

**Note:** `POST /pipeline/run` returns **202 immediately** after creating the Firestore record and dispatching the durable `chatbot-pipeline` Cloud Run job. Poll status — do not wait on the POST response.

---

## 2. Create/update worker jobs (including chatbot-pipeline)

```bash
export WORKER_IMAGE=gcr.io/${PROJECT_ID}/simasia-chatbot-worker:phase21a
export WORKER_SA=chatbot-worker@${PROJECT_ID}.iam.gserviceaccount.com

gcloud builds submit --project=${PROJECT_ID} \
  --tag ${WORKER_IMAGE} \
  --dockerfile=deploy/Dockerfile.worker .

# Child step jobs (unchanged entrypoints)
for JOB in chatbot-pipeline chatbot-drive-sync chatbot-ingest chatbot-eval chatbot-deploy; do
  gcloud run jobs update ${JOB} \
    --project=${PROJECT_ID} \
    --region=${REGION} \
    --image=${WORKER_IMAGE}
done

# Durable pipeline runner (new)
gcloud run jobs describe chatbot-pipeline --region=${REGION} --project=${PROJECT_ID} >/dev/null 2>&1 \
  && ACTION=update || ACTION=create

gcloud run jobs ${ACTION} chatbot-pipeline \
  --project=${PROJECT_ID} \
  --region=${REGION} \
  --image=${WORKER_IMAGE} \
  --service-account=${WORKER_SA} \
  --command=python \
  --args=-m,apps.worker.cli,job,pipeline \
  --memory=2Gi --cpu=2 --task-timeout=7200 --max-retries=0 \
  --set-env-vars=STACK_PROFILE=firebase,GOOGLE_CLOUD_PROJECT=${PROJECT_ID},GCS_BUCKET=${BUCKET},CLOUD_RUN_REGION=${REGION},FIRESTORE_CONTROL_PLANE=true,GCS_REGISTRY_FALLBACK=false,CLOUD_RUN_JOBS_DISABLED=false,CLOUD_RUN_JOBS_USE_GCLOUD=false,CLOUD_RUN_JOB_PREFIX=chatbot
```

`chatbot-pipeline` receives `--client-id` and `--pipeline-id` overrides per execution from the API dispatch.

---

## 3. Verify worker jobs use latest image

```bash
export WORKER_IMAGE=gcr.io/${PROJECT_ID}/simasia-chatbot-worker:phase21a

for JOB in chatbot-pipeline chatbot-drive-sync chatbot-ingest chatbot-eval chatbot-deploy; do
  gcloud run jobs describe ${JOB} --region=${REGION} --project=${PROJECT_ID} \
    --format='value(template.template.containers[0].image)'
done
```

If any job shows an old digest/tag, update:

```bash
for JOB in chatbot-pipeline chatbot-drive-sync chatbot-ingest chatbot-eval chatbot-deploy; do
  gcloud run jobs update ${JOB} \
    --project=${PROJECT_ID} \
    --region=${REGION} \
    --image=${WORKER_IMAGE}
done
```

Jobs should use entrypoint `python -m apps.worker.cli job <step> --client-id default` as base; Phase 21A dispatch **overrides args** with `--client-id <client_id>` per run.

---

## 4. IAM (run once if not already granted)

```bash
export PROJECT_ID=simasia-ai-chatbot-production
export API_SA=chatbot-api@${PROJECT_ID}.iam.gserviceaccount.com

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

`roles/run.developer` on API SA covers dispatching `chatbot-pipeline`. Pipeline orchestration and status writes run inside the worker job (Firestore + child job dispatch).

Grant worker SA the same runtime roles if not already:

```bash
export WORKER_SA=chatbot-worker@${PROJECT_ID}.iam.gserviceaccount.com
for ROLE in roles/run.developer roles/datastore.user roles/storage.objectAdmin roles/secretmanager.secretAccessor; do
  gcloud projects add-iam-policy-binding ${PROJECT_ID} \
    --member="serviceAccount:${WORKER_SA}" \
    --role="${ROLE}"
done
```

---

## 5. Pipeline smoke — ingest_eval

```bash
export API_URL=$(gcloud run services describe simasia-chatbot-api \
  --region=${REGION} --project=${PROJECT_ID} --format='value(status.url)')
export ADMIN_TOKEN='...'   # from Secret Manager

# Start pipeline (returns immediately with pipeline_id)
curl -s -X POST "${API_URL}/v1/admin/clients/default/pipeline/run" \
  -H "x-admin-token: ${ADMIN_TOKEN}" \
  -H "Content-Type: application/json" \
  -d '{"preset":"ingest_eval","eval_llm_mode":"live"}' | tee /tmp/pipeline.json

export PIPELINE_ID=$(python3 -c "import json; print(json.load(open('/tmp/pipeline.json'))['pipeline_id'])")

# Poll until terminal (succeeded/failed)
watch -n 10 "curl -s ${API_URL}/v1/admin/clients/default/pipeline/status/${PIPELINE_ID} \
  -H 'x-admin-token: ${ADMIN_TOKEN}' | jq '{status,current_step,ingest_summary,eval_summary,error}'"
```

**Expect:**

- `status=succeeded`
- `ingest_summary.sources_total` > 0, `chunks_total` > 0
- `eval_summary.status=pass`, `deploy_eligible=true`
- `step_results[].cloud_run_execution` populated for remote steps

---

## 6. Pipeline smoke — full_deploy (when eval already passed)

```bash
curl -s -X POST "${API_URL}/v1/admin/clients/default/pipeline/run" \
  -H "x-admin-token: ${ADMIN_TOKEN}" \
  -H "Content-Type: application/json" \
  -d '{"preset":"full_deploy","eval_llm_mode":"live"}' | tee /tmp/pipeline_full.json

export PIPELINE_ID=$(python3 -c "import json; print(json.load(open('/tmp/pipeline_full.json'))['pipeline_id'])")

# Poll as above
```

**Expect:**

- `active_version_after_deploy` set
- `index_manifest.active` updated
- `runtime_refresh_note` mentions API restart

---

## 7. Mark stale stuck pipelines (optional cleanup)

If pre-fix pipelines are stuck at `running` with empty `step_results`:

```bash
curl -s -X POST "${API_URL}/v1/admin/clients/default/pipeline/status/pipe_4e263452d0bb/mark-failed" \
  -H "x-admin-token: ${ADMIN_TOKEN}" \
  -H "Content-Type: application/json" \
  -d '{"reason":"Stale run from pre-21A-fix background thread."}'
```

Repeat for `pipe_65326a5de7f4` and `pipe_a1f6738b9065`.

---

## 8. Restart API after deploy

```bash
gcloud run services update simasia-chatbot-api \
  --project=${PROJECT_ID} \
  --region=${REGION} \
  --update-env-vars=PIPELINE_REFRESH_TS=$(date -u +%Y%m%dT%H%M%SZ)
```

Check startup logs for:

```
[api-runtime] active_index_version=...
[api-runtime] active_chunk_count=2797
```

---

## 9. Chat smoke

```bash
export WIDGET_KEY='wk_...'

curl -s -X POST "${API_URL}/v2/chat/respond" \
  -H "Content-Type: application/json" \
  -H "x-client-key: ${WIDGET_KEY}" \
  -H "Origin: https://www.poamskp.gr" \
  -d '{"message":"Τι είναι η ΠΟΑμΣΚΠ;"}' | jq '{answer:.answer,sources:.sources,confidence:.confidence}'
```

Contact FAQ:

```bash
curl -s -X POST "${API_URL}/v2/chat/respond" \
  -H "Content-Type: application/json" \
  -H "x-client-key: ${WIDGET_KEY}" \
  -H "Origin: https://www.poamskp.gr" \
  -d '{"message":"Πώς μπορώ να επικοινωνήσω με την ΠΟΑμΣΚΠ;"}' | jq '.answer'
```

---

## 10. Admin UI

Open react-widget admin dashboard → **Pipeline automation**:

- [ ] Run Drive Sync (`sync_only`)
- [ ] Run Ingest (`steps: ["ingest"]`)
- [ ] Run Eval (`ingest_eval`)
- [ ] Run Full Pipeline (`full_deploy`)
- [ ] Latest run shows status, ingest/eval summaries, step_results with `cloud_run_execution`

---

## 11. Manual fallback (unchanged)

```bash
gcloud run jobs execute chatbot-drive-sync --region=${REGION} --project=${PROJECT_ID} --wait
gcloud run jobs execute chatbot-ingest --region=${REGION} --project=${PROJECT_ID} --wait
gcloud run jobs execute chatbot-eval --region=${REGION} --project=${PROJECT_ID} --wait
gcloud run jobs execute chatbot-deploy --region=${REGION} --project=${PROJECT_ID} --wait
```

Use only if admin pipeline dispatch fails.
