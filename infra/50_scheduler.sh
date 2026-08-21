#!/usr/bin/env bash
# Phase 18 · Step 50 — Nightly Cloud Scheduler job → POST /enqueue-run with OIDC
# (gcp-notes §4). The job authenticates as the invoker SA; the audience is the
# service's own run.app URL. Idempotent: updates the job if it already exists.
source "$(dirname "$0")/_config.sh"
require_isolated_project

URL="$(gcloud run services describe "${RUN_SERVICE}" --region="${REGION}" \
        --format='value(status.url)' ${GCLOUD_PROJECT_FLAG})"
if [[ -z "${URL}" ]]; then
  echo "ERROR: service '${RUN_SERVICE}' has no URL — deploy it first (step 40)." >&2
  exit 1
fi
ENQUEUE_URI="${URL}/enqueue-run"
echo "==> Nightly job will POST ${ENQUEUE_URI} at '${SCHEDULER_CRON}' ${SCHEDULER_TZ}"

# The enqueue endpoint requires a run_id in the body — use the scheduled date as
# a natural, idempotent run id (one logical run per night).
BODY='{"run_id":"nightly"}'

COMMON=(
  --location="${REGION}"
  --schedule="${SCHEDULER_CRON}"
  --time-zone="${SCHEDULER_TZ}"
  --http-method=POST
  --uri="${ENQUEUE_URI}"
  --message-body="${BODY}"
  --headers="Content-Type=application/json"
  --oidc-service-account-email="${INVOKER_SA}"
  --oidc-token-audience="${URL}"
  --max-retry-attempts=3
  ${GCLOUD_PROJECT_FLAG}
)

if gcloud scheduler jobs describe "${SCHEDULER_JOB}" --location="${REGION}" \
      ${GCLOUD_PROJECT_FLAG} >/dev/null 2>&1; then
  echo "    Job exists — updating."
  gcloud scheduler jobs update http "${SCHEDULER_JOB}" "${COMMON[@]}"
else
  echo "    Creating job."
  gcloud scheduler jobs create http "${SCHEDULER_JOB}" "${COMMON[@]}"
fi
echo "==> Done. (Trigger a test run any time with:"
echo "    gcloud scheduler jobs run ${SCHEDULER_JOB} --location=${REGION} ${GCLOUD_PROJECT_FLAG} )"
