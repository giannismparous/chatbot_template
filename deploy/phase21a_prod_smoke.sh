#!/usr/bin/env bash
# Phase 21A production smoke — idempotent deploy + pipeline verification.
#
# PREFLIGHT: Do not use `gcloud builds submit --dockerfile=...` — use Cloud Build YAML.
#
# Usage:
#   export ADMIN_TOKEN="$(gcloud secrets versions access latest --secret=chatbot-admin-api-token --project=simasia-ai-chatbot-production)"
#   export WIDGET_KEY="wk_..."   # optional; required for chat smoke
#   export OLD_PIPELINES="pipe_abc,pipe_def"   # optional cleanup
#   bash deploy/phase21a_prod_smoke.sh
set -euo pipefail

PROJECT_ID="${PROJECT_ID:-simasia-ai-chatbot-production}"
REGION="${REGION:-europe-west1}"
BUCKET="${BUCKET:-simasia-chatbot-prod-simasia-ai-chatbot-production}"
CLIENT_ID="${CLIENT_ID:-default}"
API_SERVICE="${API_SERVICE:-simasia-chatbot-api}"
API_SA="chatbot-api@${PROJECT_ID}.iam.gserviceaccount.com"
WORKER_SA="chatbot-worker@${PROJECT_ID}.iam.gserviceaccount.com"
IMAGE_TAG="${IMAGE_TAG:-phase21a}"
API_IMAGE="gcr.io/${PROJECT_ID}/simasia-chatbot-api:${IMAGE_TAG}"
WORKER_IMAGE="gcr.io/${PROJECT_ID}/simasia-chatbot-worker:${IMAGE_TAG}"
PIPELINE_POLL_SECONDS="${PIPELINE_POLL_SECONDS:-30}"
PIPELINE_TIMEOUT_SECONDS="${PIPELINE_TIMEOUT_SECONDS:-7200}"
PIPELINE_RUN_TIMEOUT_SECONDS="${PIPELINE_RUN_TIMEOUT_SECONDS:-25}"
CHAT_ORIGIN="${CHAT_ORIGIN:-https://www.poamskp.gr}"
OLD_PIPELINES="${OLD_PIPELINES:-pipe_4e263452d0bb,pipe_65326a5de7f4,pipe_a1f6738b9065,pipe_2fea8723ca1c,pipe_bc77c4f88c72}"

PASS=0
FAIL=0
REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "${REPO_ROOT}"

log() { echo "[phase21a-smoke] $*"; }
fail() { log "FAIL: $*"; FAIL=$((FAIL + 1)); }
pass() { log "PASS: $*"; PASS=$((PASS + 1)); }

run_or_die() {
  local label="$1"
  shift
  log "RUN: ${label}"
  if "$@"; then
    log "OK: ${label}"
  else
    local exit_code=$?
    echo "[phase21a-smoke] FATAL: ${label} failed (exit ${exit_code})" >&2
    exit "${exit_code}"
  fi
}

build_image_with_cloudbuild_yaml() {
  local dockerfile="$1"
  local image="$2"
  local config_path="$3"
  cat >"${config_path}" <<EOF
steps:
  - name: gcr.io/cloud-builders/docker
    args: ["build", "-f", "${dockerfile}", "-t", "${image}", "."]
images:
  - "${image}"
EOF
  log "Wrote Cloud Build config ${config_path} for ${image}"
  run_or_die "gcloud builds submit (${image})" \
    gcloud builds submit --project="${PROJECT_ID}" --config="${config_path}" .
}

require_cmd() {
  command -v "$1" >/dev/null 2>&1 || { echo "Missing required command: $1" >&2; exit 2; }
}

is_json() {
  python3 -c "import json,sys; json.loads(sys.stdin.read())" >/dev/null 2>&1
}

# curl_api METHOD URL [curl-args...]  -> sets HTTP_CODE and HTTP_BODY
curl_api() {
  local method="$1"
  local url="$2"
  shift 2
  local tmp
  tmp="$(mktemp)"
  HTTP_CODE="$(curl -sS -o "${tmp}" -w '%{http_code}' -X "${method}" "${url}" "$@")"
  HTTP_BODY="$(cat "${tmp}")"
  rm -f "${tmp}"
}

jq_or_fail() {
  local label="$1"
  local body="$2"
  if ! echo "${body}" | is_json; then
    fail "${label} returned non-JSON (HTTP ${HTTP_CODE:-?})"
    log "RAW BODY: ${body}"
    return 1
  fi
  echo "${body}" | jq .
}

require_cmd gcloud
require_cmd curl
require_cmd jq
require_cmd python3

if [[ -z "${ADMIN_TOKEN:-}" ]]; then
  echo "ADMIN_TOKEN is required (x-admin-token). Do not print it in logs." >&2
  exit 2
fi

log "project=${PROJECT_ID} region=${REGION} client=${CLIENT_ID} tag=${IMAGE_TAG}"

log "Building worker image ${WORKER_IMAGE}"
build_image_with_cloudbuild_yaml \
  "deploy/Dockerfile.worker" \
  "${WORKER_IMAGE}" \
  "/tmp/cloudbuild-worker-phase21a.yaml"

log "Building API image ${API_IMAGE}"
build_image_with_cloudbuild_yaml \
  "deploy/Dockerfile.api" \
  "${API_IMAGE}" \
  "/tmp/cloudbuild-api-phase21a.yaml"

WORKER_ENV="STACK_PROFILE=firebase,GOOGLE_CLOUD_PROJECT=${PROJECT_ID},GCS_BUCKET=${BUCKET},CLOUD_RUN_REGION=${REGION},FIRESTORE_CONTROL_PLANE=true,GCS_REGISTRY_FALLBACK=false,CLOUD_RUN_JOBS_DISABLED=false,CLOUD_RUN_JOBS_USE_GCLOUD=false,CLOUD_RUN_JOB_PREFIX=chatbot"

update_child_job() {
  local job="$1"
  local args="$2"
  run_or_die "gcloud run jobs update ${job}" \
    gcloud run jobs update "${job}" \
    --project="${PROJECT_ID}" \
    --region="${REGION}" \
    --image="${WORKER_IMAGE}" \
    --service-account="${WORKER_SA}" \
    --command=python \
    --args="${args}" \
    --set-env-vars="${WORKER_ENV}" \
    --memory=2Gi --cpu=2 --task-timeout=7200 --max-retries=0
}

update_child_job chatbot-drive-sync "-m,apps.worker.cli,job,drive-sync"
update_child_job chatbot-ingest "-m,apps.worker.cli,job,ingest"
update_child_job chatbot-eval "-m,apps.worker.cli,job,eval"
update_child_job chatbot-deploy "-m,apps.worker.cli,job,deploy"

if gcloud run jobs describe chatbot-pipeline --region="${REGION}" --project="${PROJECT_ID}" >/dev/null 2>&1; then
  PIPELINE_ACTION=update
else
  PIPELINE_ACTION=create
fi
run_or_die "gcloud run jobs ${PIPELINE_ACTION} chatbot-pipeline" \
  gcloud run jobs "${PIPELINE_ACTION}" chatbot-pipeline \
  --project="${PROJECT_ID}" \
  --region="${REGION}" \
  --image="${WORKER_IMAGE}" \
  --service-account="${WORKER_SA}" \
  --command=python \
  --args=-m,apps.worker.cli,job,pipeline \
  --set-env-vars="${WORKER_ENV}" \
  --memory=2Gi --cpu=2 --task-timeout=7200 --max-retries=0

log "Deploying API ${API_SERVICE}"
run_or_die "gcloud run deploy ${API_SERVICE}" \
  gcloud run deploy "${API_SERVICE}" \
  --project="${PROJECT_ID}" \
  --region="${REGION}" \
  --image="${API_IMAGE}" \
  --service-account="${API_SA}" \
  --update-env-vars="STACK_PROFILE=firebase,GOOGLE_CLOUD_PROJECT=${PROJECT_ID},GCS_BUCKET=${BUCKET},CLOUD_RUN_REGION=${REGION},FIRESTORE_CONTROL_PLANE=true,GCS_REGISTRY_FALLBACK=false,CLOUD_RUN_JOBS_DISABLED=false,CLOUD_RUN_JOBS_USE_GCLOUD=false,CLOUD_RUN_JOB_PREFIX=chatbot,DEFAULT_CLIENT_ID=${CLIENT_ID}" \
  --update-secrets="GEMINI_API_KEY=chatbot-gemini-api-key:latest,ADMIN_API_TOKEN=chatbot-admin-api-token:latest,WIDGET_KEY_HASH_SECRET=chatbot-widget-key-hash-secret:latest,GOOGLE_DRIVE_CREDENTIALS_JSON=chatbot-drive-credentials:latest" \
  --memory=2Gi --cpu=2 --timeout=300 --min-instances=0

API_URL="$(gcloud run services describe "${API_SERVICE}" --region="${REGION}" --project="${PROJECT_ID}" --format='value(status.url)')"
log "API_URL=${API_URL}"

curl_api GET "${API_URL}/health"
if [[ "${HTTP_CODE}" == "200" ]]; then
  pass "/health returned 200"
else
  fail "/health returned ${HTTP_CODE}"
  log "RAW BODY: ${HTTP_BODY}"
fi

mark_old_pipelines_failed() {
  IFS=',' read -ra OLD_IDS <<< "${OLD_PIPELINES}"
  for pid in "${OLD_IDS[@]}"; do
    pid="$(echo "${pid}" | xargs)"
    [[ -z "${pid}" ]] && continue
    log "Marking stale pipeline failed (best-effort): ${pid}"
    curl_api POST "${API_URL}/v1/admin/clients/${CLIENT_ID}/pipeline/status/${pid}/mark-failed" \
      -H "x-admin-token: ${ADMIN_TOKEN}" \
      -H "Content-Type: application/json" \
      -d '{"reason":"Marked failed by phase21a_prod_smoke.sh"}'
    if [[ "${HTTP_CODE}" == "200" ]]; then
      log "marked ${pid} failed"
    elif [[ "${HTTP_CODE}" == "400" ]]; then
      log "skip ${pid} (already terminal): ${HTTP_BODY}"
    else
      log "warn mark-failed ${pid} HTTP ${HTTP_CODE}: ${HTTP_BODY}"
    fi
  done
}
mark_old_pipelines_failed

poll_pipeline() {
  local pipeline_id="$1"
  local label="$2"
  local deadline=$(( $(date +%s) + PIPELINE_TIMEOUT_SECONDS ))
  while [[ $(date +%s) -lt ${deadline} ]]; do
    curl_api GET "${API_URL}/v1/admin/clients/${CLIENT_ID}/pipeline/status/${pipeline_id}" \
      -H "x-admin-token: ${ADMIN_TOKEN}"
    if ! echo "${HTTP_BODY}" | is_json; then
      fail "${label} status poll returned non-JSON HTTP ${HTTP_CODE}"
      log "RAW BODY: ${HTTP_BODY}"
      sleep "${PIPELINE_POLL_SECONDS}"
      continue
    fi
    local status current_step step_count
    status="$(echo "${HTTP_BODY}" | jq -r '.status')"
    current_step="$(echo "${HTTP_BODY}" | jq -r '.current_step // empty')"
    step_count="$(echo "${HTTP_BODY}" | jq -r '.step_results | length')"
    log "${label} poll pipeline=${pipeline_id} status=${status} current_step=${current_step:-none} step_results=${step_count}"
    if [[ "${status}" == "succeeded" || "${status}" == "failed" || "${status}" == "stale" ]]; then
      echo "${HTTP_BODY}"
      return 0
    fi
    sleep "${PIPELINE_POLL_SECONDS}"
  done
  fail "${label} timed out after ${PIPELINE_TIMEOUT_SECONDS}s"
  return 1
}

run_pipeline() {
  local preset="$1"
  local label="$2"
  log "Starting ${label} preset=${preset}"
  curl_api POST "${API_URL}/v1/admin/clients/${CLIENT_ID}/pipeline/run" \
    --max-time "${PIPELINE_RUN_TIMEOUT_SECONDS}" \
    -H "x-admin-token: ${ADMIN_TOKEN}" \
    -H "Content-Type: application/json" \
    -d "{\"preset\":\"${preset}\",\"eval_llm_mode\":\"live\"}"
  log "${label} POST /pipeline/run HTTP ${HTTP_CODE}"
  if [[ "${HTTP_CODE}" != "202" ]]; then
    fail "${label} expected HTTP 202, got ${HTTP_CODE}"
    log "RAW BODY: ${HTTP_BODY}"
    return 1
  fi
  if ! echo "${HTTP_BODY}" | is_json; then
    fail "${label} /pipeline/run returned non-JSON"
    log "RAW BODY: ${HTTP_BODY}"
    return 1
  fi
  jq_or_fail "${label} /pipeline/run" "${HTTP_BODY}" >/dev/null
  local pipeline_id runner_execution
  pipeline_id="$(echo "${HTTP_BODY}" | jq -r '.pipeline_id')"
  runner_execution="$(echo "${HTTP_BODY}" | jq -r '.runner_execution // empty')"
  if [[ -z "${pipeline_id}" || "${pipeline_id}" == "null" ]]; then
    fail "${label} did not return pipeline_id"
    return 1
  fi
  log "${label} pipeline_id=${pipeline_id} runner_execution=${runner_execution:-unknown}"
  poll_pipeline "${pipeline_id}" "${label}"
}

validate_ingest_eval() {
  local body="$1"
  jq_or_fail "ingest_eval final status" "${body}"
  local status step_count chunks eval_status deploy_eligible
  status="$(echo "${body}" | jq -r '.status')"
  step_count="$(echo "${body}" | jq -r '.step_results | length')"
  chunks="$(echo "${body}" | jq -r '.ingest_summary.chunks_total // 0')"
  eval_status="$(echo "${body}" | jq -r '.eval_summary.status // empty')"
  deploy_eligible="$(echo "${body}" | jq -r '.eval_summary.deploy_eligible // false')"
  if [[ "${status}" == "succeeded" && "${step_count}" -ge 2 && "${chunks}" -gt 0 && "${eval_status}" == "pass" && "${deploy_eligible}" == "true" ]]; then
    pass "ingest_eval succeeded with ingest+eval step_results"
  else
    fail "ingest_eval acceptance failed status=${status} steps=${step_count} chunks=${chunks} eval=${eval_status}"
  fi
}

validate_full_deploy() {
  local body="$1"
  jq_or_fail "full_deploy final status" "${body}"
  local status step_count error_msg
  status="$(echo "${body}" | jq -r '.status')"
  step_count="$(echo "${body}" | jq -r '.step_results | length')"
  error_msg="$(echo "${body}" | jq -r '.error // empty')"
  if [[ "${status}" == "succeeded" ]]; then
    local active
    active="$(echo "${body}" | jq -r '.active_version_after_deploy // empty')"
    if [[ "${step_count}" -ge 4 && -n "${active}" ]]; then
      pass "full_deploy succeeded with deploy active=${active}"
    else
      fail "full_deploy succeeded but missing step_results/active"
    fi
  elif [[ "${status}" == "failed" && "${step_count}" -gt 0 && -n "${error_msg}" ]]; then
    pass "full_deploy failed with recorded step_results and error"
  else
    fail "full_deploy stuck or uninformative status=${status} steps=${step_count} error=${error_msg:-none}"
  fi
}

INGEST_EVAL_BODY="$(run_pipeline ingest_eval ingest_eval || true)"
if [[ -n "${INGEST_EVAL_BODY:-}" ]]; then
  validate_ingest_eval "${INGEST_EVAL_BODY}"
fi

FULL_DEPLOY_BODY="$(run_pipeline full_deploy full_deploy || true)"
if [[ -n "${FULL_DEPLOY_BODY:-}" ]]; then
  validate_full_deploy "${FULL_DEPLOY_BODY}"
  if echo "${FULL_DEPLOY_BODY}" | is_json && [[ "$(echo "${FULL_DEPLOY_BODY}" | jq -r '.status')" == "succeeded" ]]; then
    log "Refreshing API runtime after deploy"
    run_or_die "gcloud run services update ${API_SERVICE} (runtime refresh)" \
      gcloud run services update "${API_SERVICE}" \
      --project="${PROJECT_ID}" \
      --region="${REGION}" \
      --update-env-vars="PIPELINE_REFRESH_TS=$(date -u +%Y%m%dT%H%M%SZ)"
  fi
fi

if [[ -n "${WIDGET_KEY:-}" ]]; then
  log "Running chat smoke"
  curl_api POST "${API_URL}/v2/chat/respond" \
    -H "Content-Type: application/json" \
    -H "x-client-key: ${WIDGET_KEY}" \
    -H "Origin: ${CHAT_ORIGIN}" \
    -d '{"message":"Τι είναι η ΠΟΑμΣΚΠ;"}'
  if echo "${HTTP_BODY}" | is_json; then
    CHAT_ANSWER="$(echo "${HTTP_BODY}" | jq -r '.answer // empty')"
    if [[ -n "${CHAT_ANSWER}" ]]; then
      pass "chat smoke returned an answer"
      echo "${HTTP_BODY}" | jq '{answer,sources,confidence}'
    else
      fail "chat smoke returned empty answer"
    fi
  else
    fail "chat smoke returned non-JSON HTTP ${HTTP_CODE}"
    log "RAW BODY: ${HTTP_BODY}"
  fi
else
  log "WIDGET_KEY not set; skipping chat smoke"
fi

log "SUMMARY pass=${PASS} fail=${FAIL}"
if [[ "${FAIL}" -gt 0 ]]; then
  exit 1
fi
exit 0
