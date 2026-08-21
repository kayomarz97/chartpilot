#!/usr/bin/env bash
# Phase 18 · Step 20 — Create the Firestore Native database in asia-south1.
#
# Firestore in asia-south1 is REGIONAL only (no India multi-region) — gcp-notes §6.
# A project has at most one (default) database; creating it twice errors, so we
# check first. This is NOT a destructive script: it never deletes a database.
source "$(dirname "$0")/_config.sh"
require_isolated_project

echo "==> Checking for an existing Firestore database..."
if gcloud firestore databases describe --database='(default)' ${GCLOUD_PROJECT_FLAG} >/dev/null 2>&1; then
  echo "    (default) Firestore database already exists — skipping create."
  echo "    Verifying its location..."
  loc="$(gcloud firestore databases describe --database='(default)' \
          --format='value(locationId)' ${GCLOUD_PROJECT_FLAG})"
  echo "    location: ${loc} (expected ${REGION})"
  if [[ "${loc}" != "${REGION}" ]]; then
    echo "WARNING: existing Firestore DB is in '${loc}', not '${REGION}'." >&2
    echo "         Firestore location is IMMUTABLE — you cannot move it. If this is" >&2
    echo "         the wrong region you must create a NAMED (non-default) DB or a new" >&2
    echo "         project. Stopping so nothing is silently mis-located." >&2
    exit 1
  fi
else
  echo "    Creating Firestore Native database in ${REGION}..."
  gcloud firestore databases create --location="${REGION}" ${GCLOUD_PROJECT_FLAG}
  echo "    Done."
fi
