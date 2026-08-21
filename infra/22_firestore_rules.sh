#!/usr/bin/env bash
# Phase 18 · Step 22 (optional, defense-in-depth) — apply the deny-all Firestore
# Security Rules (infra/firestore.rules, spec §73).
#
# WHY THIS IS OPTIONAL: the backend uses the Firestore ADMIN SDK, which bypasses
# Security Rules entirely, and NO client-SDK/web app is registered against this
# project — so there is no client path to patient data in the first place. These
# rules are belt-and-suspenders: if a web API key were ever added later, they
# deny it. Applying them needs the Firebase CLI (gcloud has no Firestore-rules
# command); if it isn't installed, this script prints the one manual step and
# exits 0 rather than failing the whole deploy.
source "$(dirname "$0")/_config.sh"
require_isolated_project

cd "$(dirname "$0")"  # so firebase.json + firestore.rules resolve

if command -v firebase >/dev/null 2>&1; then
  echo "==> Deploying deny-all Firestore rules via Firebase CLI..."
  firebase deploy --only firestore:rules --project="${PROJECT_ID}"
  echo "    Done."
else
  echo "==> Firebase CLI not found — SKIPPING rules deploy (safe: Admin SDK bypasses"
  echo "    rules and no client app is registered). To apply the deny-all rules later:"
  echo "      npm install -g firebase-tools    # one-time"
  echo "      cd infra && firebase deploy --only firestore:rules --project=${PROJECT_ID}"
fi
