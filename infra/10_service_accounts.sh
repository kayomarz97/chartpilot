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

# --- Cloud Tasks OIDC enqueue chain (verified needed via live deploy 2026-08-21) ---
# For /enqueue-run (running as the runtime SA) to create tasks that carry an
# OIDC token identifying the invoker SA, THREE grants are required:
#   1. runtime SA -> cloudtasks.enqueuer            (create tasks in the queue)
#   2. runtime SA -> serviceAccountUser on invoker  (attach invoker SA to the token)
#   3. Cloud Tasks service agent -> tokenCreator on invoker (mint the token at dispatch)
# Missing any of these makes /enqueue-run return HTTP 500 ("lacks cloudtasks.tasks.create"
# or actAs denied). NOTE: IAM changes here take a few minutes to propagate before the
# first successful enqueue.
PROJECT_NUMBER="$(gcloud projects describe "${PROJECT_ID}" --format='value(projectNumber)')"
TASKS_AGENT="service-${PROJECT_NUMBER}@gcp-sa-cloudtasks.iam.gserviceaccount.com"

echo "==> 1/3 runtime SA -> roles/cloudtasks.enqueuer..."
gcloud projects add-iam-policy-binding "${PROJECT_ID}" \
  --member="serviceAccount:${RUNTIME_SA}" \
  --role="roles/cloudtasks.enqueuer" --condition=None >/dev/null

echo "==> 2/3 runtime SA -> roles/iam.serviceAccountUser on the invoker SA..."
gcloud iam service-accounts add-iam-policy-binding "${INVOKER_SA}" \
  --member="serviceAccount:${RUNTIME_SA}" \
  --role="roles/iam.serviceAccountUser" ${GCLOUD_PROJECT_FLAG} >/dev/null

echo "==> 3/3 Cloud Tasks service agent -> roles/iam.serviceAccountTokenCreator on the invoker SA..."
# The Cloud Tasks service agent is created lazily on first API use; enabling the API
# (step 00) is enough for it to exist by the time this runs.
gcloud iam service-accounts add-iam-policy-binding "${INVOKER_SA}" \
  --member="serviceAccount:${TASKS_AGENT}" \
  --role="roles/iam.serviceAccountTokenCreator" ${GCLOUD_PROJECT_FLAG} >/dev/null
echo "    Done (allow a few minutes for these to propagate before the first run)."

echo "==> (run.invoker for the invoker SA is bound to the SERVICE in step 40,"
echo "     as a resource-level binding — not a broad project-level grant.)"
