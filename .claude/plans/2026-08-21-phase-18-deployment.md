# Phase 18 — GCP Deployment (plan)

Date: 2026-08-21 · Branch: `dev` · Prev checkpoint: `phase-17` (commit 39f2153)

## Goal
Ship the deployment layer for ChartPilot: containerize the backend, expose the two
authenticated HTTP endpoints Cloud Tasks/Scheduler will call, wire the real Cloud Tasks
adapter, and provide reproducible, idempotent deploy scripts — WITHOUT touching the user's
cloud until they approve every command (TD-002, §73).

## Split: what the machine can prove vs. what the user must run

### Part A — hermetic + locally verifiable (subagent builds, Opus verifies) → satisfies the phase-18 exit gate
Everything here runs with NO real GCP, NO network, and is covered by `make check` + a local docker build.

1. **`backend/Dockerfile`** (§76A.1): multi-stage (uv deps layer separate from runtime), base pinned
   to an explicit minor/digest (no floating `latest`), non-root user, binds `$PORT` (default 8000),
   installs from the pinned `uv.lock`, NO `.env` / secret baked in.
2. **`backend/.dockerignore`** (§76A.1): excludes `.git`, `.env`, caches, unneeded fixtures/snapshots.
3. **`backend/app/api/routes.py`** — two endpoints mounted on `app.main:app`:
   - `POST /enqueue-run` (Scheduler target): calls existing `enqueue_run(...)` → returns `EnqueueResult`.
   - `POST /tasks/process-patient` (Cloud Tasks target): parses a `RunTask` body, runs the durable
     per-patient processor via an **injectable handler** (real wiring is thin/`# VERIFY-LIVE`; tests
     inject a fake). Idempotent: a terminal checkpoint short-circuits (already true in `process_patient`).
4. **`backend/app/api/auth.py`** — OIDC bearer verification dependency: verifies a Google-signed ID
   token (issuer `accounts.google.com`, audience = the service's own run.app URL from env). Injectable
   verifier so tests can exercise accept/reject hermetically. Unauthenticated → 401/403.
5. **`backend/app/tasks/cloud_tasks.py`** — real `CloudTasksQueue` implementing the `TaskQueue` Protocol
   via `google-cloud-tasks` `CreateTask` + `OidcToken` (audience = worker run.app URL), thin +
   `# VERIFY-LIVE` (same pattern as `storage/firestore_repo.py`). Not called in hermetic tests.
6. **Tests** (`backend/tests/...`): unauthenticated worker call rejected; authenticated accepted;
   idempotent re-POST of same `RunTask`; `/enqueue-run` returns `EnqueueResult`; `/health` still 200;
   `CloudTasksQueue` satisfies the `TaskQueue` Protocol (structural, no network).
7. **§76A.2 local verifications (Opus runs, records to `evidence/`)**: `docker build` from clean
   checkout; container starts; `/health` 200 with env; `/health` non-200 (503) when required env
   missing (fail loud); no secret string in the built image.

Exit gate (§65.2): `make check` → `evidence/phase_18.txt` exit 0; docker verifications recorded;
journal entry; commit + annotated tag `phase-18`; `git status` clean; secret-scanner clean.

### Part B — real cloud (USER runs; Opus writes scripts + shows every command first) → enables Phase 19
Reproducible, idempotent scripts under `infra/` (§76: `set -euo pipefail`, validate env, idempotent,
never delete unrelated resources, explicit `--project=chartpilot-agentic`). I will NOT run these.

- `infra/00_enable_apis.sh` — enable run, cloudtasks, cloudscheduler, firestore, cloudbuild, artifactregistry.
- `infra/10_service_accounts.sh` — runtime SA (`roles/datastore.user`) + invoker SA (`roles/run.invoker` on the service).
- `infra/20_firestore.sh` — create Firestore Native DB in asia-south1.
- `infra/30_tasks_queue.sh` — create the Cloud Tasks queue.
- `infra/40_deploy_run.sh` — build image + `gcloud run deploy --no-allow-unauthenticated`, set env (incl. GEMINI_API_KEY via `--set-secrets` from Secret Manager, NOT plaintext).
- `infra/50_scheduler.sh` — nightly Scheduler job → `/enqueue-run` with OIDC.
- `infra/60_smoke.sh` — Phase 19 smoke (enqueue one patient, poll Firestore).

## Isolation guardrails (TD-002)
Every script hard-codes/validates `--project=chartpilot-agentic` and refuses to run if the active
gcloud project differs. No existing project is ever referenced. GEMINI_API_KEY goes through Secret
Manager, never baked into the image or a script. Iatronix untouched.

## Operating model
Sonnet subagent builds Part A; Opus writes the brief, independently re-runs `make check` + the docker
verifications, writes Part B scripts, commits + tags. Subagent never commits/tags/pushes.
