#!/usr/bin/env bash
# Phase 18 · Step 70 — Build + deploy the Next.js frontend to Cloud Run (PUBLIC).
#
# The frontend renders entirely from baked-in synthetic demo data (frontend/lib/
# mockData.ts) — no backend calls, no env vars, no secrets — so it is safe to
# serve publicly (--allow-unauthenticated) as the judge-facing demo site. It is a
# SEPARATE Cloud Run service from the private backend API.
source "$(dirname "$0")/_config.sh"
require_isolated_project

FRONTEND_DIR="$(cd "$(dirname "$0")/../frontend" && pwd)"
FE_SERVICE="chartpilot-frontend"
FE_IMAGE="${REGION}-docker.pkg.dev/${PROJECT_ID}/${AR_REPO}/${FE_SERVICE}:${IMAGE_TAG}"

echo "==> Building frontend image ${FE_IMAGE} (Cloud Build)..."
gcloud builds submit "${FRONTEND_DIR}" --tag "${FE_IMAGE}" ${GCLOUD_PROJECT_FLAG}

echo "==> Deploying PUBLIC Cloud Run service '${FE_SERVICE}'..."
gcloud run deploy "${FE_SERVICE}" \
  --image="${FE_IMAGE}" \
  --region="${REGION}" \
  --allow-unauthenticated \
  --cpu=1 --memory=512Mi \
  ${GCLOUD_PROJECT_FLAG}

FE_URL="$(gcloud run services describe "${FE_SERVICE}" --region="${REGION}" \
          --format='value(status.url)' ${GCLOUD_PROJECT_FLAG})"
echo ""
echo "==> Frontend LIVE (public):"
echo "    ${FE_URL}"
