#!/usr/bin/env bash
# Phase 18 · Step 25 — Store the Gemini API key in Secret Manager (never in an
# image, script, or env-var literal — §73 / project rule "secrets in .env / secret store").
#
# This script creates the SECRET CONTAINER and grants the runtime SA read access.
# It does NOT hard-code the key. You add the key VALUE yourself, interactively,
# in the printed one-liner — so the key never lands in this file, your shell
# history (printf from stdin), or git.
source "$(dirname "$0")/_config.sh"
require_isolated_project

echo "==> Ensuring Secret Manager secret '${SECRET_NAME}' exists..."
if gcloud secrets describe "${SECRET_NAME}" ${GCLOUD_PROJECT_FLAG} >/dev/null 2>&1; then
  echo "    Secret '${SECRET_NAME}' already exists — skipping create."
else
  gcloud secrets create "${SECRET_NAME}" --replication-policy="automatic" ${GCLOUD_PROJECT_FLAG}
  echo "    Created secret container '${SECRET_NAME}' (no version/value yet)."
fi

echo "==> Granting the runtime SA read access to the secret..."
gcloud secrets add-iam-policy-binding "${SECRET_NAME}" \
  --member="serviceAccount:${RUNTIME_SA}" \
  --role="roles/secretmanager.secretAccessor" \
  ${GCLOUD_PROJECT_FLAG} >/dev/null
echo "    Done."

# Has a value been added yet?
if gcloud secrets versions list "${SECRET_NAME}" ${GCLOUD_PROJECT_FLAG} \
     --format='value(name)' 2>/dev/null | grep -q .; then
  echo "    A secret version already exists. To ROTATE the key, run the add-version"
  echo "    command below with the new key."
else
  echo ""
  echo "    ACTION REQUIRED — add the key value now (paste when prompted, then Ctrl-D):"
  echo "      gcloud secrets versions add ${SECRET_NAME} ${GCLOUD_PROJECT_FLAG} --data-file=-"
fi
