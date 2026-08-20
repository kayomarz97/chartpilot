# GCP research notes — chartpilot-agentic (region: asia-south1 / Mumbai)

Retrieved: 2026-08-20. Sources: `cloud.google.com` / `docs.cloud.google.com` (official docs now
redirect `cloud.google.com/*` → `docs.cloud.google.com/*`, same content, different host — both
cited below as they appeared), plus the installed Python SDK source (ground truth for anything
docs left ambiguous) and one real-world GitHub issue used only to confirm an exact error string,
not as a source of truth for the number itself (the number is corroborated by the SDK-adjacent
docs and search results below).

Scope note: item 6 (Gemini/Vertex AI availability) is **not** one of the three planned SDKs: it
was researched because the task asked about it as an asia-south1 gotcha. Findings there are
weaker (no single authoritative locations table was fetchable) and are flagged as such.

---

## 1. Firestore (Phase 12 — most important)

### Mode
**Native mode** is correct (as planned) — this project needs documents/subcollections/queries,
not the legacy Datastore key-value model. Confirmed both Standard and Enterprise editions offer
Native mode as a `--type` option (see below).

### Create the database in asia-south1
```bash
gcloud firestore databases create \
  --database=DATABASE_ID \
  --location=asia-south1 \
  --edition=standard \
  --type=firestore-native
```
- `--type=firestore-native` (vs `datastore-mode`) selects Native mode.
- `--edition=standard` vs `enterprise` (Enterprise adds e.g. `--enable-realtime-updates`,
  MongoDB-compatible access — not needed here).
- `asia-south1` (Mumbai) **is a valid regional Firestore location.** It is **regional only** —
  there is no Asia/South-Asia **multi-region** Firestore location. The only Firestore
  multi-regions found in the docs are `eur3` and `nam5`/`nam7` (Europe/N. America). If you ever
  want multi-region durability for this data, that means replicating across regional databases
  yourself — not a built-in option for India.
- Source: https://docs.cloud.google.com/firestore/docs/manage-databases (read 2026-08-20);
  region list: https://docs.cloud.google.com/firestore/docs/locations (read 2026-08-20).

### THE NUMBER: writes per transaction / batched write
**500 writes (operations) per `Commit` call — this covers both a single transaction and a
single `WriteBatch`.** This is a hard, server-enforced limit (not a soft quota you can raise by
billing tier).

- The current official quotas page (`docs.cloud.google.com/firestore/quotas`) explicitly states
  only: *"Maximum number of field transformations that can be performed on a single document in
  a `Commit` operation or in a transaction: 500."* It does **not**, in its current wording, spell
  out "500 writes" in one sentence the way older Firebase docs used to.
- Corroboration for the actual enforced number (server-side, applies to whole Commit, not just
  field transforms):
  - Firestore transactions doc: *"A batched write with hundreds of documents might require many
    index updates and might exceed the limit on transaction size"* — guidance is to shrink the
    batch or use BulkWriter/parallel individual writes.
    https://docs.cloud.google.com/firestore/docs/manage-data/transactions (read 2026-08-20)
  - Real production error text (GitHub issue, Teleport project hitting the live API):
    `"maximum 500 writes allowed per request"` — https://github.com/gravitational/teleport/issues/12007
    (read 2026-08-20). Used only to confirm the number that both the docs and community sources
    (Qualdesk, oneuptime.com engineering posts) consistently cite as 500.
  - **I did not find one single current official page that states "500" in a clean, unambiguous
    "max writes per transaction/batch" sentence — flag this explicitly.** The 500 figure is
    consistent across every source checked (docs prose, live error message, multiple third-party
    write-ups), so treat it as reliable, but if you want a belt-and-suspenders design, chunk
    artifact writes at **≤ 400** per batch to leave headroom, since field-transform ops
    (`SERVER_TIMESTAMP`, `Increment`, `ArrayUnion`) each also count against the same 500 ceiling
    and are easy to lose track of inside a loop.
- The `google-cloud-firestore` **Python SDK itself does not client-side-enforce** this limit
  (checked source of the installed package, v2.28.1 wheel — no `MAX_BATCH_SIZE`/500 constant in
  `base_batch.py`, `transaction.py`); it's purely a server-side rejection on `Commit`. Design
  your chunking logic explicitly — don't rely on the client library to tell you when to split.

### Other hard limits relevant to your design
| Limit | Value | Source |
|---|---|---|
| Max document size | 1 MiB (1,048,576 bytes) | firestore quotas page |
| Max size of a single field value | 1 MiB − 89 bytes (1,048,487 bytes) | same |
| Max depth of nested maps/arrays | 20 | same |
| Max subcollection depth | 100 | same |
| Max API request size (a whole Commit) | 10 MiB | same |
| Transaction wall-clock limit | 270 seconds total, 60-second idle expiry | same |
| Write rate to a collection with a monotonically increasing/decreasing indexed field (e.g. a timestamp index) | 500 writes/sec, workaroundable via a shard field ("sharded timestamps" pattern) | same + https://docs.cloud.google.com/firestore/native/docs/solutions/shard-timestamp |
| **Sustained writes/sec to a single document** | **No official hard number found.** Docs describe it as workload-dependent ("depends highly on the workload... write rate, contention among requests, number of affected indexes") and warn of "hotspotting" under sustained concurrent writes to one doc. This directly affects your per-stage summary doc: treat frequent single-document updates as a soft risk, not a fixed quota, and don't fire concurrent writers at the same summary doc. | https://docs.cloud.google.com/firestore/native/docs/understand-reads-writes-scale (read 2026-08-20) |

Source for the table (except sharded-timestamps and write-rate-to-single-doc rows, cited inline):
https://docs.cloud.google.com/firestore/quotas (read 2026-08-20, redirected from
`cloud.google.com/firestore/quotas`).

### Python SDK: package + minimal examples
- Package: `google-cloud-firestore`. **Latest on PyPI as of 2026-08-20: 2.28.1** (installed in
  this environment: 2.28.0 — bump it). Verify against your actual lockfile/`pyproject.toml`
  before writing code; if it pins an older 2.x, the API below is stable across 2.x.

**Transaction** (atomic read-then-write; needed if a stage read depends on prior state):
```python
from google.cloud import firestore

db = firestore.Client()  # picks up project from ADC/env
transaction = db.transaction()

@firestore.transactional
def update_in_transaction(transaction, doc_ref):
    snapshot = doc_ref.get(transaction=transaction)
    transaction.update(doc_ref, {"population": snapshot.get("population") + 1})

doc_ref = db.collection("cities").document("SF")
update_in_transaction(transaction, doc_ref)
```

**Batched write to your subcollection shape** (`runs/{run}/patients/{pid}/claims/{cid}`),
chunked to stay under the 500-op ceiling:
```python
from google.cloud import firestore

db = firestore.Client()

def write_claims_chunked(run_id: str, pid: str, claims: list[dict], chunk_size: int = 400):
    base = db.collection("runs").document(run_id) \
             .collection("patients").document(pid) \
             .collection("claims")
    for i in range(0, len(claims), chunk_size):
        batch = db.batch()
        for claim in claims[i:i + chunk_size]:
            claim_ref = base.document(claim["id"])
            batch.set(claim_ref, claim)
        batch.commit()
```
Source (transaction/batch shapes):
https://docs.cloud.google.com/firestore/docs/manage-data/transactions (read 2026-08-20).

**BulkWriter** — mentioned by the docs as the alternative for large, *non-atomic* write volumes
(it ramps up throughput, starting at and capped by an internal default of **500 ops/sec**,
confirmed directly in the installed SDK source, `bulk_writer.py`:
`initial_ops_per_second: int = 500`, `max_ops_per_second: int = 500`). Use it only when you don't
need all-or-nothing atomicity across the chunk — for your per-patient claim writes, prefer the
chunked `WriteBatch` above since you likely want each chunk atomic.

---

## 2. Cloud Run

- **Max request timeout: 3600 seconds (60 minutes).** Default is 300 seconds (5 minutes).
  Flag: `--timeout` (accepts seconds as an int, or a duration string like `1m20s`).
  Source: https://docs.cloud.google.com/run/docs/configuring/request-timeout (read 2026-08-20).
- **asia-south1 is supported for Cloud Run** (listed under Tier 1 pricing regions). GPU-backed
  Cloud Run in `asia-south1` specifically is called out as **"available by invitation only"** —
  irrelevant to this plan (no GPU use), but flag it if that ever changes.
  Source: https://docs.cloud.google.com/run/docs/locations (read 2026-08-20).
- **Deploy from source vs container:**
  - `gcloud run deploy --source .` — builds via Cloud Build + Google Cloud buildpacks
    automatically, no local Docker required. Documented as **"a convenience feature [that] does
    not allow full customization of the build."**
  - For full control (custom base image, multi-stage Dockerfile, pinned build steps): build with
    `gcloud builds submit` (or plain `docker build` + push) then `gcloud run deploy --image=...`.
  - Source: https://docs.cloud.google.com/run/docs/deploying-source-code (read 2026-08-20).
- **Require authentication (no public invocations):**
  - At deploy time: `gcloud run deploy SERVICE --no-allow-unauthenticated`
  - On an existing public service, revoke public access:
    `gcloud run services remove-iam-policy-binding SERVICE --member="allUsers" --role="roles/run.invoker"`
  - Source: https://docs.cloud.google.com/run/docs/authenticating/public (read 2026-08-20).
- **Invoking from Cloud Tasks/Scheduler with OIDC:**
  - Grant the caller's service account `roles/run.invoker` on the Cloud Run service:
    ```bash
    gcloud run services add-iam-policy-binding SERVICE \
      --member="serviceAccount:CALLER_SA@PROJECT_ID.iam.gserviceaccount.com" \
      --role="roles/run.invoker"
    ```
  - Cloud Tasks/Scheduler then attach a Google-signed OIDC ID token to each request
    automatically once configured with the service account + audience (see §3/§4 below); you
    don't hand-mint tokens for these callers.
  - The token's `audience` must be the **Cloud Run service's own run.app URL, not a custom
    domain** — explicitly called out as unsupported for audience matching.
  - Header: `Authorization: Bearer ID_TOKEN` (or `X-Serverless-Authorization` if `Authorization`
    is already used by your own app-level auth).
  - Source: https://docs.cloud.google.com/run/docs/authenticating/service-to-service (read
    2026-08-20).

---

## 3. Cloud Tasks

- **asia-south1 is a supported Cloud Tasks location** ("`asia-south1` | Mumbai, India").
  Source: https://docs.cloud.google.com/tasks/docs/locations (read 2026-08-20).
- **Create a queue** (exact flag surface from the gcloud reference):
  ```bash
  gcloud tasks queues create QUEUE_ID \
    --location=asia-south1 \
    --max-attempts=MAX_ATTEMPTS \
    --max-retry-duration=MAX_RETRY_DURATION \
    --min-backoff=MIN_BACKOFF \
    --max-backoff=MAX_BACKOFF \
    --max-doublings=MAX_DOUBLINGS \
    --max-dispatches-per-second=MAX_DISPATCHES_PER_SECOND \
    --max-concurrent-dispatches=MAX_CONCURRENT_DISPATCHES
  ```
  Source: https://docs.cloud.google.com/sdk/gcloud/reference/tasks/queues/create (read
  2026-08-20).
- **Default retry config for a new queue** (from a sample `queue describe` shown in the configuring-queues doc):
  `maxAttempts: 100`, `minBackoff: 0.100s`, `maxBackoff: 3600s` (1 hour), `maxDoublings: 16`.
  No explicit default stated for `maxRetryDuration` in the fetched excerpt — treat as unbounded
  unless you set it. **Confirm this against `gcloud tasks queues describe` output on your actual
  queue before relying on it** — this table came from a docs example, not a guaranteed universal
  default.
  Source: https://docs.cloud.google.com/tasks/docs/configuring-queues (read 2026-08-20).
- **Enqueue an HTTP task with OIDC to an authenticated Cloud Run URL** (Python,
  `google-cloud-tasks`, current PyPI version **2.24.0** as of 2026-08-20):
  ```python
  from google.cloud import tasks_v2

  def create_http_task_with_token(
      project: str,
      location: str,
      queue: str,
      url: str,
      payload: bytes,
      service_account_email: str,
      audience: str | None = None,
  ) -> tasks_v2.Task:
      client = tasks_v2.CloudTasksClient()
      task = tasks_v2.Task(
          http_request=tasks_v2.HttpRequest(
              http_method=tasks_v2.HttpMethod.POST,
              url=url,
              oidc_token=tasks_v2.OidcToken(
                  service_account_email=service_account_email,
                  audience=audience,
              ),
              body=payload,
          ),
      )
      return client.create_task(
          tasks_v2.CreateTaskRequest(
              parent=client.queue_path(project, location, queue),
              task=task,
          )
      )
  ```
  Source: https://docs.cloud.google.com/tasks/docs/creating-http-target-tasks (read 2026-08-20).
- **De-duplication via task `name`:** if you set an explicit task `name` (rather than letting
  Cloud Tasks generate one), Cloud Tasks uses it to dedupe. **The dedup window is up to 24
  hours** after a task with that name is deleted or completes before the same name can be reused
  — **up to 9 days** if the queue was created via a legacy `queue.yaml`/`queue.xml` (App Engine
  style config, not your case if you create the queue with `gcloud`/Terraform).
  Exact quote: *"The IDs of deleted tasks are not immediately available for reuse. It can take up
  to 24 hours (or 9 days if the task's queue was created using a queue.yaml or queue.xml) for the
  task ID to be released and made available again."*
  Source: https://docs.cloud.google.com/tasks/docs/reference/rest/v2/projects.locations.queues.tasks/create
  (read 2026-08-20). Design implication: for per-patient idempotent enqueue-dedup (e.g. name tasks
  `run-{run_id}-patient-{pid}`), don't expect immediate reuse of a name after retrying a failed
  run within the same day — pick names that are unique per attempt if you need guaranteed
  re-enqueue, or accept the 24h collision window as your dedup guarantee.

---

## 4. Cloud Scheduler

- **asia-south1 is a supported Cloud Scheduler location** ("`asia-south1` / Mumbai, India").
  Source: https://docs.cloud.google.com/scheduler/docs/locations (read 2026-08-20).
- **Timezone:** `--time-zone` flag, **default `Etc/UTC`**, accepts IANA tz database names —
  `Asia/Kolkata` is a standard IANA zone name and is supported (the flag docs explicitly show
  `Asia/Kolkata` as an example format). For literal UTC, pass the string `utc`.
  Source: https://docs.cloud.google.com/sdk/gcloud/reference/scheduler/jobs/create/http (read
  2026-08-20).
- **Nightly cron hitting Cloud Run with OIDC** — full sequence from the official Cloud
  Run-triggered-by-Scheduler doc:
  ```bash
  # 1. Service account for Scheduler to invoke as
  gcloud iam service-accounts create SCHEDULER_SA_NAME \
    --display-name "Cloud Scheduler invoker"

  # 2. Grant it permission to invoke the Cloud Run service
  gcloud run services add-iam-policy-binding SERVICE \
    --member="serviceAccount:SCHEDULER_SA_NAME@PROJECT_ID.iam.gserviceaccount.com" \
    --role="roles/run.invoker"

  # 3. Create the nightly job
  gcloud scheduler jobs create http nightly-job \
    --location=asia-south1 \
    --schedule="0 2 * * *" \
    --time-zone="Asia/Kolkata" \
    --http-method=POST \
    --uri="https://SERVICE-xxxxx-el.a.run.app/your-nightly-endpoint" \
    --oidc-service-account-email="SCHEDULER_SA_NAME@PROJECT_ID.iam.gserviceaccount.com" \
    --oidc-token-audience="https://SERVICE-xxxxx-el.a.run.app"
  ```
  Source: https://docs.cloud.google.com/run/docs/triggering/using-scheduler (read 2026-08-20).
- **Retry flags & defaults** (`gcloud scheduler jobs create http`):
  `--max-retry-attempts` (0–5, **default 0** — i.e. no retry unless you set this),
  `--max-retry-duration` (default 0 = unlimited, measured from first run),
  `--min-backoff` (default `5s`), `--max-backoff` (default `3600s`), `--max-doublings`
  (default `5`). **Note the Scheduler defaults differ from Tasks' queue defaults above (0 max
  retries vs. Tasks' 100) — set `--max-retry-attempts` explicitly for the nightly job if you want
  retries on transient Cloud Run failures.**
  Source: https://docs.cloud.google.com/sdk/gcloud/reference/scheduler/jobs/create/http (read
  2026-08-20).
- **`roles/iam.serviceAccountTokenCreator` — checked explicitly, not required for the standard
  same-project flow above.** The official HTTP-target-auth page states only that the *Cloud
  Scheduler service agent* itself needs `roles/cloudscheduler.serviceAgent` (which it has by
  default once the API is enabled) and does not mention granting Token Creator to anything for
  the documented same-project OIDC setup. Community reports (GitHub, security forums) describe
  needing `serviceAccountTokenCreator` in **cross-project** service-account scenarios — not your
  setup (single project `chartpilot-agentic`). Flagging so you don't add an unneeded broad grant.
  Source: https://docs.cloud.google.com/scheduler/docs/http-target-auth (read 2026-08-20).

---

## 5. IAM least-privilege — roles/service accounts

| Purpose | Service account | Role(s) | Notes |
|---|---|---|---|
| Cloud Run runtime SA (reads/writes Firestore) | dedicated SA, e.g. `chartpilot-run-sa@chartpilot-agentic.iam.gserviceaccount.com` | `roles/datastore.user` | *"Read/write access to data in a Firestore database. Intended for application developers and service accounts."* Do **not** use `roles/datastore.owner` (index/import/backup admin — unneeded) or the Compute Engine default SA. |
| Cloud Scheduler invoker SA | dedicated SA per job or shared "invokers" SA | `roles/run.invoker` on the target Cloud Run service (resource-level binding, not project-level) | Attached via `--oidc-service-account-email` on the job. |
| Cloud Tasks invoker SA | dedicated SA (can be the same as Scheduler's or separate) | `roles/run.invoker` on the target Cloud Run service | Attached via `oidc_token.service_account_email` on each task. |

Predefined Firestore roles for reference: `roles/datastore.owner` (full access),
`roles/datastore.user` (read/write app data — what you want), `roles/datastore.viewer`
(read-only). Source: https://docs.cloud.google.com/firestore/docs/security/iam (read
2026-08-20).

**OIDC wiring, restated simply:** Scheduler/Tasks don't need broad IAM on Firestore — they only
ever call your Cloud Run URL. The Run service itself, running as its own dedicated runtime SA,
is what touches Firestore. Keep those two identities (invoker SA vs. runtime SA) separate so a
compromised Scheduler/Tasks config can never directly read/write patient data — it can only ever
trigger the Run service, which enforces its own auth via `--no-allow-unauthenticated` +
`roles/run.invoker`.

---

## 6. asia-south1 gotchas — summary

| Service | asia-south1 status | Source |
|---|---|---|
| Firestore Native mode | Supported, **regional only** (no India/South-Asia multi-region option) | firestore/docs/locations |
| Cloud Run | Supported (Tier 1 pricing). GPU workloads in this region are invitation-only (not relevant here) | run/docs/locations |
| Cloud Tasks | Supported | tasks/docs/locations |
| Cloud Scheduler | Supported | scheduler/docs/locations |
| Vertex AI Gemini (for calling the LLM from your Run service) | **Weaker evidence — flagged, not fully verified.** Web search (not an official locations table I could fetch cleanly) indicates Gemini models are available via Vertex AI in `asia-south1`, but a Google AI Developer forum thread asks whether any model *more capable than Gemini 2.5 Flash* is available there, implying the most-capable/newest models may land in `asia-south1` later than in `us-central1` or only via the **global** Vertex AI endpoint. **Action before Phase 18 wiring:** re-check `docs.cloud.google.com/vertex-ai/generative-ai/docs/learn/locations` for the exact model you intend to call, and consider using the Vertex AI **global** endpoint for the Gemini call specifically (keeping Cloud Run/Tasks/Scheduler/Firestore all in `asia-south1` for data residency + latency) rather than assuming full model parity in-region. Do not treat this row as verified fact — it needs a fresh docs-researcher pass scoped to Vertex AI locations specifically when Phase 18 starts. |

No other gaps found: all four core infra services (Run, Tasks, Scheduler, Firestore) are
confirmed available in `asia-south1` as of 2026-08-20, so there is no forced reason to split
infra across regions for the planned architecture.

---

## Package versions referenced (PyPI, checked 2026-08-20)
- `google-cloud-firestore` — latest 2.28.1 (environment had 2.28.0 installed)
- `google-cloud-tasks` — latest 2.24.0
- `google-cloud-scheduler` — latest 2.20.0

Pin exact versions in `pyproject.toml`/`requirements.txt` and re-run `docs-researcher` if you
bump major versions later — 2.x → 3.x could change import paths.
