#!/usr/bin/env bash
# Phase 18 · Step 30 — Create the Cloud Tasks queue (gcp-notes §3).
# Idempotent: an existing queue is left as-is (we never delete/recreate — that
# would drop in-flight tasks). Retry knobs are set explicitly rather than relying
# on undocumented defaults.
source "$(dirname "$0")/_config.sh"
require_isolated_project

echo "==> Ensuring Cloud Tasks queue '${TASKS_QUEUE}' in ${REGION}..."
if gcloud tasks queues describe "${TASKS_QUEUE}" --location="${REGION}" \
      ${GCLOUD_PROJECT_FLAG} >/dev/null 2>&1; then
  echo "    Queue '${TASKS_QUEUE}' already exists — leaving its config untouched."
else
  gcloud tasks queues create "${TASKS_QUEUE}" \
    --location="${REGION}" \
    --max-attempts=5 \
    --min-backoff=10s \
    --max-backoff=300s \
    --max-doublings=3 \
    --max-dispatches-per-second=10 \
    --max-concurrent-dispatches=5 \
    ${GCLOUD_PROJECT_FLAG}
  echo "    Created queue '${TASKS_QUEUE}'."
fi

echo "==> Current queue config:"
gcloud tasks queues describe "${TASKS_QUEUE}" --location="${REGION}" \
  --format='yaml(name,rateLimits,retryConfig,state)' ${GCLOUD_PROJECT_FLAG}
