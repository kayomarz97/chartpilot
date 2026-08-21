#!/usr/bin/env bash
# Phase 18 · Step 40 — Build the image and deploy the Cloud Run service (gcp-notes §2).
#
# Flow (all idempotent / safe to re-run):
#   1. Ensure the Artifact Registry repo exists.
#   2. Build + push the backend image from backend/Dockerfile (Cloud Build).
#   3. Deploy PRIVATE (--no-allow-unauthenticated) as the runtime SA, with the
#      Gemini key mounted from Secret Manager (never a plaintext env literal).
#   4. Read back the service URL and set OIDC_AUDIENCE + WORKER_URL to it, so the
#      service can (a) verify inbound OIDC tokens and (b) enqueue tasks to itself.
#   5. Bind the invoker SA run.invoker on THIS service (resource-level, not project).
source "$(dirname "$0")/_config.sh"
require_isolated_project

BACKEND_DIR="$(cd "$(dirname "$0")/../backend" && pwd)"

# 1. Artifact Registry repo -------------------------------------------------
echo "==> Ensuring Artifact Registry repo '${AR_REPO}' in ${REGION}..."
if gcloud artifacts repositories describe "${AR_REPO}" --location="${REGION}" \
      ${GCLOUD_PROJECT_FLAG} >/dev/null 2>&1; then
  echo "    Repo '${AR_REPO}' already exists."
else
  gcloud artifacts repositories create "${AR_REPO}" \
    --repository-format=docker --location="${REGION}" \
    --description="ChartPilot backend images" ${GCLOUD_PROJECT_FLAG}
fi

# 2. Build + push -----------------------------------------------------------
echo "==> Building image ${IMAGE_URI} from ${BACKEND_DIR}/Dockerfile (Cloud Build)..."
gcloud builds submit "${BACKEND_DIR}" --tag "${IMAGE_URI}" ${GCLOUD_PROJECT_FLAG}

# 3. Initial private deploy -------------------------------------------------
echo "==> Deploying Cloud Run service '${RUN_SERVICE}' (PRIVATE)..."
gcloud run deploy "${RUN_SERVICE}" \
  --image="${IMAGE_URI}" \
  --region="${REGION}" \
  --no-allow-unauthenticated \
  --service-account="${RUNTIME_SA}" \
  --set-env-vars="GCP_PROJECT_ID=${PROJECT_ID},GCP_REGION=${REGION},MODEL_A_ID=${MODEL_A_ID},MODEL_B_ID=${MODEL_B_ID},TASKS_QUEUE=${TASKS_QUEUE},TASKS_INVOKER_SA=${INVOKER_SA}" \
  --set-secrets="GEMINI_API_KEY=${SECRET_NAME}:latest" \
  --timeout=600 \
  --cpu=1 --memory=1Gi \
  ${GCLOUD_PROJECT_FLAG}

# 4. Read URL, wire self-referential audience/worker-url ---------------------
URL="$(gcloud run services describe "${RUN_SERVICE}" --region="${REGION}" \
        --format='value(status.url)' ${GCLOUD_PROJECT_FLAG})"
echo "==> Service URL: ${URL}"
echo "==> Setting OIDC_AUDIENCE + WORKER_URL to the service URL..."
gcloud run services update "${RUN_SERVICE}" --region="${REGION}" \
  --update-env-vars="OIDC_AUDIENCE=${URL},WORKER_URL=${URL}/tasks/process-patient" \
  ${GCLOUD_PROJECT_FLAG}

# 5. Allow the invoker SA to call this service ------------------------------
echo "==> Granting invoker SA run.invoker on '${RUN_SERVICE}' (resource-level)..."
gcloud run services add-iam-policy-binding "${RUN_SERVICE}" --region="${REGION}" \
  --member="serviceAccount:${INVOKER_SA}" \
  --role="roles/run.invoker" ${GCLOUD_PROJECT_FLAG} >/dev/null

echo ""
echo "==> Deployed. Service URL:"
echo "    ${URL}"
echo "    (private — only the invoker SA, via OIDC, can call it)"
