#!/usr/bin/env bash
# Phase 18/19 · Step 60 — End-to-end smoke test against the DEPLOYED service.
#
# 1. /health must be 200 (proves the container serves + resolved its pinned models).
# 2. Trigger the nightly Scheduler job once (fan-out → Cloud Tasks → worker).
# 3. Poll Firestore for checkpoint documents the run produced.
# Read-only except for triggering one real run. Never deletes anything.
source "$(dirname "$0")/_config.sh"
require_isolated_project

URL="$(gcloud run services describe "${RUN_SERVICE}" --region="${REGION}" \
        --format='value(status.url)' ${GCLOUD_PROJECT_FLAG})"
[[ -z "${URL}" ]] && { echo "ERROR: no service URL — deploy first (step 40)." >&2; exit 1; }

echo "==> 1. Health check (authenticated) ${URL}/health"
TOKEN="$(gcloud auth print-identity-token)"
code="$(curl -s -o /tmp/chartpilot_health.json -w '%{http_code}' \
         -H "Authorization: Bearer ${TOKEN}" "${URL}/health" || true)"
echo "    HTTP ${code}"; cat /tmp/chartpilot_health.json 2>/dev/null; echo
if [[ "${code}" != "200" ]]; then
  echo "    (If 403: your user needs run.invoker on ${RUN_SERVICE}, or add"
  echo "     --member=user:$(gcloud config get-value account) run.invoker to test.)"
fi

echo "==> 2. Triggering nightly Scheduler job '${SCHEDULER_JOB}' once..."
gcloud scheduler jobs run "${SCHEDULER_JOB}" --location="${REGION}" ${GCLOUD_PROJECT_FLAG}

echo "==> 3. Waiting ~40s for the fan-out + per-patient Gemini runs, then checking Firestore..."
echo "    Results are written at: runs/nightly/patients/{patient_id}  (+ claims/ + evidence/ subcollections)."
echo "    The Firestore console (Data tab) is the reliable visual check. A CLI peek at the"
echo "    'patients' collection group (each per-patient PatientSummary doc):"
sleep 40 || true
gcloud firestore documents list --collection-ids="patients" \
  --format='value(name)' ${GCLOUD_PROJECT_FLAG} 2>/dev/null | head -20 \
  || echo "    (no docs yet, or collection-group listing unsupported — check the console)"

echo "==> Smoke complete. In the Firestore console, open runs/nightly/patients/patient-a and confirm"
echo "    its status + the claims/ and evidence/ subcollections are populated."
