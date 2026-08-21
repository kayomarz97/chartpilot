#!/usr/bin/env bash
# ChartPilot deployment — shared configuration + isolation guardrail.
#
# EVERY infra script sources this file. It hard-codes the isolated project
# (TD-002) and REFUSES to run against any other project, so a stray active
# gcloud config can never make these scripts touch Iatronix or any existing
# project. Nothing here is a secret: the project id and region are not
# sensitive; the Gemini API key is NEVER placed here (it lives in Secret
# Manager — see 25_secret.sh).
set -euo pipefail

# ---- Fixed identifiers for the isolated ChartPilot project -----------------
export PROJECT_ID="chartpilot-agentic"     # the NEW, isolated GCP project (TD-002)
export REGION="asia-south1"                 # Mumbai — all infra co-located here

# Cloud Run service
export RUN_SERVICE="chartpilot-api"

# Artifact Registry (container image home)
export AR_REPO="chartpilot"
export IMAGE_TAG="${IMAGE_TAG:-v1}"         # override: IMAGE_TAG=v2 ./40_deploy_run.sh
export IMAGE_URI="${REGION}-docker.pkg.dev/${PROJECT_ID}/${AR_REPO}/${RUN_SERVICE}:${IMAGE_TAG}"

# Service accounts (least privilege — §73 / gcp-notes §5)
export RUNTIME_SA_NAME="chartpilot-run-sa"      # Cloud Run runtime identity → Firestore
export INVOKER_SA_NAME="chartpilot-invoker-sa"  # Scheduler + Tasks → invoke Run (run.invoker)
export RUNTIME_SA="${RUNTIME_SA_NAME}@${PROJECT_ID}.iam.gserviceaccount.com"
export INVOKER_SA="${INVOKER_SA_NAME}@${PROJECT_ID}.iam.gserviceaccount.com"

# Cloud Tasks
export TASKS_QUEUE="chartpilot-queue"

# Cloud Scheduler
export SCHEDULER_JOB="chartpilot-nightly"
export SCHEDULER_CRON="0 2 * * *"           # 02:00 nightly
export SCHEDULER_TZ="Asia/Kolkata"

# Secret Manager
export SECRET_NAME="gemini-api-key"

# Pinned model ids (must match config/models.yaml)
export MODEL_A_ID="gemini-3.7-flash"
export MODEL_B_ID="gemini-3.5-flash"

# ---- Guardrail: prove we are pointed at the isolated project ---------------
# Any script that mutates cloud state calls this first. It does two things:
#   1. Confirms the project actually exists and you can see it.
#   2. Pins --project on every gcloud call via GCLOUD_PROJECT_FLAG, so we never
#      rely on the ambient `gcloud config get project` (which might be Iatronix).
export GCLOUD_PROJECT_FLAG="--project=${PROJECT_ID}"

require_isolated_project() {
  echo "==> Target project: ${PROJECT_ID}  region: ${REGION}"
  local active
  active="$(gcloud config get-value project 2>/dev/null || true)"
  if [[ "${active}" != "${PROJECT_ID}" ]]; then
    echo "    NOTE: active gcloud project is '${active:-<unset>}', not '${PROJECT_ID}'."
    echo "          That is fine — every command below pins ${GCLOUD_PROJECT_FLAG} explicitly."
    echo "          Nothing will touch '${active:-<unset>}'."
  fi
  if ! gcloud projects describe "${PROJECT_ID}" >/dev/null 2>&1; then
    echo "ERROR: cannot see project '${PROJECT_ID}'. Are you logged in (gcloud auth login)"
    echo "       and is billing linked? Aborting so nothing is created in the wrong place." >&2
    exit 1
  fi
  echo "    OK: project '${PROJECT_ID}' is visible."
}
