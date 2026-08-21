#!/usr/bin/env bash
# Phase 18 · Step 10 — Create least-privilege service accounts (§73, gcp-notes §5).
#
# Two SEPARATE identities, deliberately (gcp-notes §5):
#   - runtime SA  : what Cloud Run RUNS AS. Touches Firestore + reads the Gemini
#                   secret. Gets roles/datastore.user (NOT owner) + secret access.
#   - invoker SA  : what Scheduler & Tasks authenticate AS to CALL Cloud Run.
#                   Gets ONLY roles/run.invoker on the one service (bound in step 40).
# Keeping them apart means a compromised Scheduler/Tasks config can only trigger
# the service, never directly read/write patient data.
#
# Idempotent: re-creating an existing SA is caught and skipped; re-adding an
# existing IAM binding is a no-op.
source "$(dirname "$0")/_config.sh"
require_isolated_project

create_sa() {  # name, display
  if gcloud iam service-accounts describe "${1}@${PROJECT_ID}.iam.gserviceaccount.com" \
        ${GCLOUD_PROJECT_FLAG} >/dev/null 2>&1; then
    echo "    SA ${1} already exists — skipping create."
  else
    gcloud iam service-accounts create "${1}" --display-name="${2}" ${GCLOUD_PROJECT_FLAG}
    echo "    Created SA ${1}."
  fi
}

echo "==> Creating service accounts..."
create_sa "${RUNTIME_SA_NAME}" "ChartPilot Cloud Run runtime"
create_sa "${INVOKER_SA_NAME}" "ChartPilot Scheduler/Tasks invoker"

echo "==> Granting the runtime SA read/write on Firestore (roles/datastore.user)..."
gcloud projects add-iam-policy-binding "${PROJECT_ID}" \
  --member="serviceAccount:${RUNTIME_SA}" \
  --role="roles/datastore.user" \
  --condition=None >/dev/null
echo "    Done."

echo "==> (run.invoker for the invoker SA is bound to the SERVICE in step 40,"
echo "     as a resource-level binding — not a broad project-level grant.)"
