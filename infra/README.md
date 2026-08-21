# ChartPilot — Deployment runbook (Phase 18 Part B)

These scripts deploy ChartPilot to the **isolated** GCP project `chartpilot-agentic`
in `asia-south1`. They are **reproducible, idempotent, and least-privilege** (spec §73/§76).
Every script pins `--project=chartpilot-agentic` and refuses to touch any other project
(TD-002) — your existing projects (incl. Iatronix) are never referenced.

> **Nothing here has been run yet.** Claude wrote these for you to review and execute.
> Run them **in order**, reading each one first. Each is safe to re-run.

## One-time prerequisites (you do these once, by hand)
1. `gcloud auth login` — log in as the account that owns `chartpilot-agentic`.
2. Confirm billing is linked to `chartpilot-agentic` (Console → Billing).
3. `gcloud auth configure-docker asia-south1-docker.pkg.dev` — only needed if you ever
   build locally instead of via Cloud Build (the scripts use Cloud Build, so optional).

## Order
| # | Script | What it does | Cost |
|---|--------|--------------|------|
| 00 | `00_enable_apis.sh` | Enable Run/Tasks/Scheduler/Firestore/Build/Artifact/Secret APIs | free |
| 10 | `10_service_accounts.sh` | Runtime SA (Firestore) + invoker SA (calls Run) | free |
| 20 | `20_firestore.sh` | Firestore Native DB in asia-south1 | ~free (usage-billed) |
| 25 | `25_secret.sh` | Secret Manager container for the Gemini key + grant runtime SA read | ~free |
| — | *(add the key value — the exact one-liner is printed by step 25)* | | |
| 30 | `30_tasks_queue.sh` | Cloud Tasks queue | ~free (usage-billed) |
| 40 | `40_deploy_run.sh` | Build image + deploy PRIVATE Cloud Run + wire OIDC audience | build + run compute |
| 50 | `50_scheduler.sh` | Nightly job → `/enqueue-run` with OIDC | ~free |
| 60 | `60_smoke.sh` | Phase 19: health + trigger one run + check Firestore | 1 real Gemini run |

Run:
```bash
cd infra
./00_enable_apis.sh
./10_service_accounts.sh
./20_firestore.sh
./25_secret.sh          # then run the printed 'secrets versions add' one-liner with your key
./30_tasks_queue.sh
./40_deploy_run.sh
./50_scheduler.sh
./60_smoke.sh           # Phase 19 smoke
```

## Security model (why this is safe)
- **Private service:** `--no-allow-unauthenticated` — the public internet cannot call it.
- **Two identities:** the runtime SA (touches Firestore + reads the key) is separate from the
  invoker SA (only allowed to *call* the service). A leaked Scheduler/Tasks config can trigger
  the service but never read patient data directly.
- **Key in Secret Manager**, mounted at deploy — never baked into the image, a script, or a
  plaintext env var. Rotate anytime with `gcloud secrets versions add gemini-api-key --data-file=-`.
- **Isolation:** the guardrail in `_config.sh` aborts if it can't see `chartpilot-agentic`, and
  every gcloud call pins the project — no reliance on your ambient `gcloud config`.

## Teardown (if you want to remove everything after judging)
```bash
gcloud run services delete chartpilot-api --region=asia-south1 --project=chartpilot-agentic
gcloud scheduler jobs delete chartpilot-nightly --location=asia-south1 --project=chartpilot-agentic
gcloud tasks queues delete chartpilot-queue --location=asia-south1 --project=chartpilot-agentic
# Firestore data + the project itself: delete in the Console if desired.
```
