#!/usr/bin/env bash
# Phase 18 · Step 00 — Enable the GCP APIs ChartPilot needs.
# Idempotent: enabling an already-enabled API is a no-op. Touches ONLY
# ${PROJECT_ID}. Enables nothing outside the services listed.
source "$(dirname "$0")/_config.sh"
require_isolated_project

APIS=(
  run.googleapis.com                 # Cloud Run
  cloudtasks.googleapis.com          # Cloud Tasks
  cloudscheduler.googleapis.com      # Cloud Scheduler
  firestore.googleapis.com           # Firestore
  cloudbuild.googleapis.com          # Cloud Build (image build)
  artifactregistry.googleapis.com    # Artifact Registry (image store)
  secretmanager.googleapis.com       # Secret Manager (Gemini key)
  iam.googleapis.com                 # service accounts
)

echo "==> Enabling APIs on ${PROJECT_ID} (idempotent)..."
gcloud services enable "${APIS[@]}" ${GCLOUD_PROJECT_FLAG}
echo "==> Done. Enabled:"
printf '    - %s\n' "${APIS[@]}"
