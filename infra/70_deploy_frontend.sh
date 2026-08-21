#!/usr/bin/env bash
# Phase 18/21 · Step 70 — Build + deploy the Next.js frontend to Cloud Run (PUBLIC).
#
# The frontend is the ONLY public surface. Its server-side /api/runs route
# proxies the PRIVATE backend's read-only results: it runs as a dedicated
# service account that holds roles/run.invoker on chartpilot-api, mints an OIDC
# identity token from the metadata server, and calls the backend server-side.
# The browser never talks to the backend directly, so the backend stays private
# (--no-allow-unauthenticated). The UI falls back to bundled demo data if the
# proxy fails, so it's never broken.
source "$(dirname "$0")/_config.sh"
require_isolated_project

FRONTEND_DIR="$(cd "$(dirname "$0")/../frontend" && pwd)"
FE_SERVICE="chartpilot-frontend"
FE_IMAGE="${REGION}-docker.pkg.dev/${PROJECT_ID}/${AR_REPO}/${FE_SERVICE}:${IMAGE_TAG}"
FE_SA_NAME="chartpilot-frontend-sa"
FE_SA="${FE_SA_NAME}@${PROJECT_ID}.iam.gserviceaccount.com"
BACKEND_URL="${BACKEND_URL:-https://chartpilot-api-zkhsg5lcca-el.a.run.app}"

# Dedicated frontend runtime SA (least privilege: it may ONLY invoke the backend)
if ! gcloud iam service-accounts describe "${FE_SA}" ${GCLOUD_PROJECT_FLAG} >/dev/null 2>&1; then
  gcloud iam service-accounts create "${FE_SA_NAME}" \
    --display-name="ChartPilot frontend (invokes backend read API)" ${GCLOUD_PROJECT_FLAG}
fi
echo "==> Granting frontend SA run.invoker on the backend service (resource-level)..."
gcloud run services add-iam-policy-binding "${RUN_SERVICE}" --region="${REGION}" \
  --member="serviceAccount:${FE_SA}" --role="roles/run.invoker" ${GCLOUD_PROJECT_FLAG} >/dev/null

echo "==> Building frontend image ${FE_IMAGE} (Cloud Build)..."
gcloud builds submit "${FRONTEND_DIR}" --tag "${FE_IMAGE}" ${GCLOUD_PROJECT_FLAG}

echo "==> Deploying PUBLIC Cloud Run service '${FE_SERVICE}' (proxies backend ${BACKEND_URL})..."
gcloud run deploy "${FE_SERVICE}" \
  --image="${FE_IMAGE}" \
  --region="${REGION}" \
  --allow-unauthenticated \
  --service-account="${FE_SA}" \
  --set-env-vars="BACKEND_URL=${BACKEND_URL}" \
  --cpu=1 --memory=512Mi \
  ${GCLOUD_PROJECT_FLAG}

FE_URL="$(gcloud run services describe "${FE_SERVICE}" --region="${REGION}" \
          --format='value(status.url)' ${GCLOUD_PROJECT_FLAG})"
echo ""
echo "==> Frontend LIVE (public):"
echo "    ${FE_URL}"
