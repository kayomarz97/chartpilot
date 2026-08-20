# Project Playbook — doctor_helper / chartpilot-agentic

## External service & API notes

### 2026-08-20 — GCP: Firestore, Cloud Run, Cloud Tasks, Cloud Scheduler (region asia-south1)
Full research: `/root/projects/doctor_helper/research/gcp-notes.md` (read that file for exact
gcloud commands, code snippets, and every source URL — this entry is the compressed pointer).

- **Firestore transaction/batched-write hard limit: 500 writes (ops) per `Commit`.**
  Server-enforced, not client-enforced (checked `google-cloud-firestore` 2.28.x source — no
  client-side guard). Chunk artifact writes at ≤400/batch for headroom. No official hard number
  found for sustained writes/sec to one document — treat frequent updates to a single summary
  doc as a soft hotspotting risk, not a fixed quota.
- Firestore Native mode, `asia-south1`: `gcloud firestore databases create --database=ID
  --location=asia-south1 --edition=standard --type=firestore-native`. Regional only — no
  India/South-Asia multi-region option exists.
- Cloud Run max request timeout: 3600s (60 min), default 300s. `asia-south1` supported (Tier 1
  pricing; GPU there is invite-only, irrelevant here).
- Require auth: `gcloud run deploy SERVICE --no-allow-unauthenticated`. Invoke from
  Tasks/Scheduler via OIDC + `roles/run.invoker` on the caller SA; audience must be the Run
  service's own `.run.app` URL, not a custom domain.
- Cloud Tasks: `asia-south1` supported. Task-name dedup window is up to 24h after
  delete/complete (9 days for legacy `queue.yaml` queues) — don't assume immediate name reuse.
  Default queue retry: `maxAttempts: 100`, `minBackoff: 0.1s`, `maxBackoff: 3600s`,
  `maxDoublings: 16` (verify with `gcloud tasks queues describe` — docs example, not a
  guaranteed universal default).
- Cloud Scheduler: `asia-south1` supported, `--time-zone=Asia/Kolkata` works (IANA name,
  default is `Etc/UTC`). **Default `--max-retry-attempts` is 0 (no retry)** — set explicitly for
  the nightly job. `roles/iam.serviceAccountTokenCreator` not required for same-project OIDC
  setup per official docs (only shows up in cross-project community reports).
- IAM: Run runtime SA → `roles/datastore.user` (not `owner`). Scheduler/Tasks invoker SA(s) →
  `roles/run.invoker` on the Run service only — keep separate from the runtime SA so a
  Scheduler/Tasks misconfig can never touch Firestore directly.
- Gemini/Vertex AI model availability in `asia-south1` — **not fully verified**, only web-search
  evidence, no clean official locations table fetched. Re-check
  `docs.cloud.google.com/vertex-ai/generative-ai/docs/learn/locations` for the specific model at
  Phase 18 time; consider the Vertex AI **global** endpoint for the Gemini call while keeping
  everything else in `asia-south1`.
- Package versions on PyPI as of 2026-08-20: `google-cloud-firestore` 2.28.1,
  `google-cloud-tasks` 2.24.0, `google-cloud-scheduler` 2.20.0.
