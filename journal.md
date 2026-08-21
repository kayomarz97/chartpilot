# Project Journal — doctor_helper (Pre-Clinic Chart-Prep Agent)

## Current Status
Phase: 19 COMPLETE (live composition root — deployed worker actually processes patients). Committed + tag phase-19.
PHASE 19 (Sonnet built, Opus independently verified): the deployed Cloud Run worker now REALLY runs the pipeline.
  - app/demo_data/: packaged 5 patient bundles + evidence_snapshot.json under app/ (ships in image; tests/ is
    .dockerignore'd). Verified in image at /app/app/demo_data (6 files). No FHIR pagination → no other fixtures.
  - app/api/composition.py: run_demo_patient (PURE, injected deps — hermetically tested with FakeGemini +
    InMemoryRunRepository) → run_patient(...) with real deps. Idempotency §46: get_patient_summary terminal →
    short-circuit (no re-run on Cloud Tasks redelivery). live_process_patient_handler wires REAL
    GeminiInteractionsClient (A+B from settings) + FirestoreRunRepository (# VERIFY-LIVE, only 2 real-net seams).
    DemoAppointmentSource (5 demo IDs); build_live_queue (fail-loud naming missing settings).
  - PATIENT-ID SUBTLETY (documented): run_patient persists under the bundle's FHIR Patient.id (hyphenated
    "patient-a"), NOT the filename. So DEMO_PATIENT_IDS = hyphenated FHIR ids; _bundle_ref_for_patient_id maps
    "patient-a"→"patient_a.json". Idempotency check + scheduler enqueue both use the hyphenated id. Consistent
    end-to-end (scheduler run_id=nightly → runs/nightly/patients/patient-a in Firestore).
  - config.py +tasks_queue/worker_url/tasks_invoker_sa/firestore_database (optional). routes.py providers now
    return the REAL objects (no more NotImplementedError). Dockerfile models.yaml comment corrected (handler is
    decoupled from models.yaml; that's only the optional not-run-in-container pin-verify gate).
VERIFY (Opus, independent — 2026-08-21): make check PHASE=19 exit 0, 317 passed. test_composition.py 11/11
  (all 5 patients end-to-end hermetic + idempotency + endpoint + queue builder). Docker rebuild OK, demo_data
  ships, /health 200. evidence/phase_19.txt.
DESIGN CHOICE (honest): the deployed worker uses the single-shot run_patient + FirestoreRunRepository (real
  result persistence: runs/{run_id}/patients/{pid} + claims/ + evidence/ subcollections), NOT the per-stage
  process_patient/Checkpoint machinery (which stays hermetically unit-tested as the durability design). The
  returned Checkpoint is a synthesized status record (counters=0, documented). Firestore CheckpointStore not
  built — RunRepository persistence is the meaningful durable write. Fine for demo; note if scaling.
INFRA (Part B, Opus-authored, NOT run): infra/{_config,00_enable_apis,10_service_accounts,20_firestore,
  22_firestore_rules,25_secret,30_tasks_queue,40_deploy_run,50_scheduler,60_smoke}.sh + firestore.rules +
  firebase.json + README.md. All bash -n clean; every gcloud pinned --project=chartpilot-agentic + guardrail.
Next action: USER runs infra/ steps 00→60 (exact instructions in chat) = Phase 18 Part B deploy + Phase 19 live
  smoke on real infra. Then Phase 20 self-audit (§80/§81; NO video per user). Rotate the pasted Gemini key.
--- Phase 18 Part A detail (superseded header) ---
Phase: 18 PART A COMPLETE (deployment layer — hermetic + locally Docker-verified). Committed + tag phase-18.
PHASE 18 SPLIT: Part A = machine-checkable container + endpoints + auth + real CloudTasksQueue + tests (DONE,
  this session). Part B = actual gcloud deploy to isolated chartpilot-agentic — scripts written under infra/,
  NOT run (they touch the user's cloud + cost money; user runs them, TD-002). Phase 19 smoke = infra/60_smoke.sh.
PART A DELIVERED (Sonnet built, Opus independently verified):
  - backend/Dockerfile (multi-stage; base pinned to python:3.11-slim@sha256:9c900dea9e8fb7e...; non-root uid1000;
    $PORT via shell-exec CMD; uv --frozen --no-dev) + backend/.dockerignore.
  - app/api/auth.py: require_oidc dependency — FAIL-CLOSED if oidc_audience unset; injectable verifier;
    google.oauth2.id_token.verify_oauth2_token (# VERIFY-LIVE).
  - app/api/routes.py: POST /enqueue-run (Scheduler → enqueue_run), POST /tasks/process-patient (Tasks →
    process_patient handler). Both OIDC-protected. Providers injectable; real defaults = loud NotImplementedError
    (Phase 19 live wiring), NOT fake stubs. RetryableStageError → 500 → Cloud Tasks redelivery.
  - app/tasks/cloud_tasks.py: CloudTasksQueue (TaskQueue Protocol) — lazy gRPC client (offline-safe construct),
    OIDC token, name-based dedup via AlreadyExists→False. Mirrors firestore_repo # VERIFY-LIVE pattern.
  - config.py: +optional oidc_audience. main.py: mounted api_router. Tests: test_api_endpoints.py,
    test_cloud_tasks_queue.py (auth reject/accept, idempotency, EnqueueResult, Protocol structural).
  - deps google-cloud-tasks + google-auth (were pre-added by dead Phase-18 subagent; kept, uv.lock frozen-clean).
VERIFY (Opus, independent — 2026-08-21): make check PHASE=18 exit 0, 306 passed. Docker §76A.2: build exit 0;
  /health 200 with env; /health 503 fail-loud without env (names missing fields); non-root uid1000; NO .env in
  image; 0 secret patterns in image layers. evidence/phase_18.txt + evidence/phase_18_docker.txt.
TWO HONEST DEFERRALS TO PHASE 19 (flagged, not hidden):
  1. config/models.yaml lives OUTSIDE backend/ build context → NOT in the image. Safe now (nothing wired calls
     load_model_pin; handler is a NotImplementedError stub). Dockerfile documents 2 fixes for Phase 19.
  2. /health checks Settings only, NOT live pinned-model resolution (§8/§76A.1 "incl. pinned-model resolution").
     Full §76A.1 health needs the models.yaml gap fixed + a live model-pin check — Phase 19 when the real
     handler is wired.
INFRA (Part B, Opus-authored, NOT run): infra/{_config,00_enable_apis,10_service_accounts,20_firestore,
  25_secret,30_tasks_queue,40_deploy_run,50_scheduler,60_smoke}.sh + README.md. Idempotent, set -euo pipefail,
  every gcloud pinned --project=chartpilot-agentic + guardrail aborts if project not visible. Key via Secret
  Manager (never baked). Two SAs: runtime (datastore.user) vs invoker (run.invoker on service). All bash -n clean.
Next action: USER runs infra/ steps 00→60 (exact instructions given in chat) to do the actual deploy (Phase 18
  Part B) + Phase 19 smoke. Then Phase 20 self-audit (§80/§81; NO video per user). If user wants, wire the real
  Phase 19 handler (live FHIR/Gemini/Firestore composition root) + fix the 2 deferrals above before deploy.
--- prior Phase 17 detail below (superseded header) ---
Phase: 17 COMPLETE (latency + evaluation + resilience fix + README).
LATENCY FINAL (honest, both sessions recorded): Session A 44/58s (≤90s MET); Session B 125/189/193s (NOT MET).
  ≤90s ACHIEVABLE but NOT reliably met — dominated by Model A (gemini-3.7-flash) call latency (~150s under
  load, ~seconds when light). Levers: thinking_level=low, faster Model A, trim input. Demo uses precomputed
  path (instant); live path is variable. Recorded in EVALUATION.md + README.md. Not faked.
--- prior Phase 17 detail below (superseded header) ---
Phase: 17 (was: nearly complete)
Step: per-stage timing in run_patient; precomputed multi-patient run (§50); EVALUATION.md; README.md (§79).
  RESILIENCE FIX (surfaced by live latency run's transient Gemini 500 crash): gemini.py bounded retry
  (max_retries=3) + runner.py fail-closed (model exception → FAILED, never crash) + 2 resilience tests.
  make check PHASE=17 exit 0, 292 tests. SECURITY: fixed secret_scan.sh dodge (see Mistakes) — scanner now
  stronger (catches AQ. key format + quoted literals).
LIVE MEASUREMENTS (Opus, 2026-08-20, our .env key):
  - LATENCY (Patient A): run1=43.64s, run2=57.74s — both ≤90s target MET. (Clean per-stage re-run in progress.)
  - MODEL B §22.3: Set D 7/7 (100%) blocked pre-B; Set M 8/8 (100%) caught, 0 false-accept; CONTROL
    false-reject 3/4 (75%) — OVER the ≤20% ceiling → release_threshold_met=False → **ADVISORY, badge WITHHELD**.
    Model B is over-aggressive (great sensitivity, poor specificity on correct claims). Recorded honestly in
    EVALUATION.md + README.md; NOT tuned-to-fit (§22.3). Deterministic gates remain authoritative.
Next action: finish clean latency re-run → fill EVALUATION.md latency table → commit + tag phase-17. Then
  PHASE 18 — GCP deploy (SHOW gcloud commands to user FIRST; isolated chartpilot-agentic; build HTTP
  endpoints + Dockerfile + real adapters wiring), 19 (smoke), 20 (self-audit; NO video per user).

## Superseded status log
Phase: 16 COMPLETE (hermetic CI enforced). Proceeding to Phase 17.
Step: pytest-socket 0.8.1; addopts "--disable-socket --allow-unix-socket -m 'not live'" (unix socket needed
  for FastAPI TestClient asyncio self-pipe). make check PHASE=16 exit 0, 284 tests + 1 live deselected —
  suite proven network-free. tests/live/ (marked live+enable_socket, skips w/o key; run via `make live-test`
  = `cd backend && uv run pytest tests/live -m live`). Cassettes annotated _meta (model ids + 2026-08-20).
  test_no_prose_assertions.py (AST scan, §23). NOTE: ambient shell GEMINI_API_KEY != our backend/.env key
  (subagent flagged; ours is the isolated one).
Next action: PHASE 17 — latency + eval. Instrument run_patient per-stage timing; scripts/measure_latency.py
  (single-patient ≤90s p50/worst, LIVE — Opus runs); precomputed multi-patient run artifact (§50, hermetic);
  scripts/measure_model_b_live.py (§22.3 Set M live catch/false-accept/false-reject — Opus runs); EVALUATION.md.
  Then 18 (deploy — SHOW gcloud first), 19 (smoke), 20 (self-audit, no video).

## Superseded status log
Phase: 15 COMPLETE (adversarial suite). Proceeding to Phase 16.
Step: tests/adversarial/ — §53 injection invariant (byte-equality, no exception clause: benign vs
  injection vs fabricated-fact note → identical deterministic projection; K rule fires identically at 6.2);
  fabricated resource/value/citation → REJECTED; §13 stale/conflict → REQUIRES_REVIEW; §67 coverage ledger
  (greps referenced tests so a stale ref fails build). tests/support/fake_gemini.py shared. `make check
  PHASE=15` exit 0, 278 tests. Opus verified the injection test is genuine byte-equality.
Next action: PHASE 16 — hermetic CI: prove make check makes ZERO live/network calls (pytest-socket disable);
  @pytest.mark.live layer excluded by default (addopts -m "not live") in tests/live/; cassettes annotated
  with model id + retrieval date; no test asserts exact model prose. Then 17 (latency + live Model-B
  metrics + EVALUATION.md), 18 (deploy — show gcloud first), 19 (smoke), 20 (self-audit, no video).

## Superseded status log
Phase: 14 COMPLETE (demo fixtures + end-to-end pipeline + LIVE Gemini verified). Proceeding to Phase 15.
Step: app/pipeline/runner.py chains all phases (FETCHING→…→PERSISTED, fail-closed). 5 demo patients A-E
  (FHIR fixtures). Demo evidence FETCHED REAL (one-time): openFDA lisinopril was AMBIGUOUS (68 tied labels,
  no NDA) → select_label correctly raised LabelSelectionAmbiguous on live data → used enalapril (same ACE
  class); real PubMed PMID 42618199. Snapshot ebe894943f90727b. Cassettes cite real spans. `make check
  PHASE=14` exit 0, 255 tests. Opus verified runner.py + re-ran make check.
MILESTONE — FIRST LIVE END-TO-END (Opus ran real Gemini A=3.7-flash/B=3.5-flash on Patient A):
  status=flagged_for_review/persisted/committed, 6 findings. Patient facts VERIFIED; critical-hyperkalemia
  POSSIBLE_CONCERN VERIFIED with a REAL pubmed verified_span + Model B supported; a review-suggestion where
  Model B DISAGREED (insufficient_evidence) → REQUIRES_REVIEW (routed to human, not averaged); a
  PENDING-guideline claim → PARTIALLY_VERIFIED. Everything per spec on real models. VERIFY-LIVE #2 (Interactions
  API response mapping in gemini.py) RESOLVED — real calls work. VERIFY-LIVE #1 already resolved (Phase 7).
Next action: PHASE 15 — adversarial suite: §53 prompt-injection invariant (byte-equal deterministic verdict
  with/without injected free-text notes, no exception clause); fabricated resource/value/citation rejected;
  §13 source conflict; §67 high-priority coverage map. Hermetic. Then 16, 17, 18 (deploy — show gcloud), 19, 20 (no video).

## Superseded status log
Phase: 13 COMPLETE (frontend UI). Proceeding in order to Phase 14.
Step: frontend/ Next.js 15.5.23 + React 19.2.8 + TS strict, CSS design tokens (dark M3-inspired), typed mock
  data layer (5 demo patients incl. FLAGGED/COMPLETED-no-findings/FAILED/DEAD_LETTER). EvidenceDrawer §58
  showpiece (focus-trapped dialog, all provenance fields). Timeline §59. FAILED/DEAD_LETTER distinct from
  EmptyState §60. a11y §57A: vitest+jest-axe 3/3 pass, ZERO serious/critical; prefers-reduced-motion honored.
  GATE: `pnpm run build` exit 0 (5 routes SSG) + a11y pass. evidence/phase_13.txt. Opus re-ran build+a11y,
  read EvidenceDrawer.tsx. NOTE: frontend gate is pnpm build + a11y (NOT the Python make check).
Next action: PHASE 14 — demo fixtures (hand-authored FHIR bundles for patients A–E §51) + wire the full
  pipeline end-to-end (Phase 4-12) into a runnable local run, exercising LIVE Gemini Model A+B (resolves the
  last VERIFY-LIVE #2: Interactions.create response mapping). Deterministic fixture outputs. Feeds real data
  to the frontend (replace mock). Then 15 (adversarial), 16 (hermetic CI), 17 (latency + live Model-B metrics),
  18 (GCP deploy — show gcloud first), 19 (smoke), 20 (self-audit + demo video).

## Superseded status log
Phase: 12 COMPLETE (Firestore persistence + §45A two-phase, hermetic). Proceeding in order to Phase 13.
Step: app/storage/ (PatientSummary §44 compact; chunk_documents ≤400 [Firestore 500/commit limit];
  RunRepository Protocol + InMemory fake w/ fault-injection + thin real google-cloud-firestore adapter
  VERIFY-LIVE; two_phase.finalize_patient_result §45A). infra/firestore.rules deny-by-default §73.
  `make check PHASE=12` exit 0, 243 tests. google-cloud-firestore==2.28.1. Opus verified two_phase.py + rules.
GCP research DONE → research/gcp-notes.md (Firestore 500/commit; asia-south1 has all infra; Gemini Dev API
  is global so region caveat N/A). Playbook pointer in .claude/PLAYBOOK.md.
Next action: PHASE 13 — frontend (Next.js dark Material-3 UI + evidence drawer §58 + timeline §59) against a
  typed MOCK data layer (real API wiring Phase 18/19); a11y §57A (axe zero critical/serious + reduced-motion +
  keyboard); FAILED/DEAD_LETTER render distinct from "no high-priority findings" §60; production build passes.
  Then 14 (demo fixtures + real end-to-end), 15-17, 18 (deploy — show gcloud first), 19, 20.

## Superseded status log
Phase: 11 COMPLETE (durable orchestration logic, hermetic). Proceeding in order to Phase 12.
Step: app/tasks/ (RunTask, ExecutionBudget/Counters, Checkpoint §45; CheckpointStore + TaskQueue +
  AppointmentSource Protocols w/ in-memory fakes; orchestrator.process_patient idempotent/resumable/
  budgeted §45/§46/§47; enqueue_run §48 zero-appts=success; tomorrow_ist §28A.2). `make check PHASE=11`
  exit 0, 227 tests. Opus verified orchestrator.py. GCP project = chartpilot-agentic (#124294464754), billing on.
Next action: GCP DOCS RESEARCH (deferred from Phase 0) → research/gcp-notes.md (Firestore Native + txn/batch
  op limit for §45A; Cloud Run OIDC/timeout; Cloud Tasks dedup/retry/dead-letter; Cloud Scheduler cron
  Asia/Kolkata; IAM least-priv; asia-south1 gaps). THEN Phase 12 — Firestore persistence: subcollections §44,
  two-phase atomic finalization §45A (chunk >500-op writes), CommitStatus; hermetic via in-memory fake +
  thin real google-cloud-firestore adapter (untested live, like gemini.py). Real DB/deploy = Phase 18.
NOTE (refinement): orchestrator auto-completes a stage with no registered runner — Phase 14 wiring must
  register all 9 stages; consider a strict mode later.

## Superseded status log
Phase: 10 COMPLETE. BATCH 8→10 DONE. Phases 0-10 all complete + tagged. Pinged user.
Step: app/gate/ (claim_gate finalize_claim_verdict §42; patient_state derive_patient_status +
  assert_state_invariants §43). `make check PHASE=10` exit 0, 211 tests. Opus verified both (deterministic
  fail can never be VERIFIED; COMPLETED requires PERSISTED+COMMITTED).
MILESTONE: Phases 0-10 = the complete reasoning+safety "brain" (FHIR read → normalize → validity/rules →
  evidence → Model A → citation gates → Model B → final safety gate). All deterministic/hermetic; 211 tests.
Next action: PHASE 11 — durable orchestration (Cloud Scheduler → Cloud Run /enqueue → Cloud Tasks →
  /tasks/process-patient → Firestore checkpoints; idempotency; retry/dead-letter; §45/§45B/§46/§47).
  ⚠️ NEEDS: GCP research (deferred from Phase 0) + the new isolated GCP project (chartpilot-agentic) created
  by the user + billing. Do GCP docs research FIRST, then show all gcloud commands before running (TD-002).
  Phases 12 (Firestore), 13 (frontend), 14 (demo fixtures), 15 (adversarial), 16 (hermetic), 17 (latency +
  LIVE Model-B measurement), 18 (deploy), 19 (smoke), 20 (self-audit) remain.
Pending user items: (1) create GCP project + billing before Phase 11; (2) rotate the Gemini key post-build.

## Superseded status log
Phase: 7 COMPLETE (Gemini Model A integration, hermetic). `make check PHASE=07` exit 0, 147 tests.
Step: app/agent/ (protocol, models=Claim schema §40, claims parse fail-closed, toolcall §10 strict-match,
  model_pin §8 loud-fail, prompts fixed system instruction, gemini.py real adapter). config/models.yaml
  pinned (A=3.7-flash, B=3.5-flash). New make-check gate: no_sampling_params. google-genai==2.18.1 +
  pyyaml added. Opus verified models.py/toolcall.py/check script; re-ran make check.
Next action: PHASE 8 — deterministic citation checker (Gates 1-4: source retrieval, content hash, verbatim
  SPAN verification w/ §17 normalization, metadata) over the evidence snapshot; model-emitted offsets
  rejected; absent span REJECT; ambiguous multi-match FLAG_FOR_REVIEW; changed-snapshot invalidation.
  Then Phase 9 (Model B), Phase 10 (safety gate). Continue via Sonnet subagents; Opus verifies.
GEMINI KEY: RECEIVED + LIVE-VERIFIED (2026-08-20). Key is in backend/.env (gitignored, newer AQ.… format,
  len 53 — authenticates fine). Live `client.models.list()` returns 50 models incl. both pins. VERIFY-LIVE #1
  RESOLVED: names ARE `models/`-prefixed → fixed gemini.py `list_models()` to strip prefix; live
  `verify_pinned_models` now PASSES. VERIFY-LIVE #2 (internal-submodule import) still stands for SDK bumps.
  Interactions.create response mapping NOT yet live-exercised (only models.list was) — do a tiny live claims
  call at Phase 14/17. Added backend/tests/conftest.py so tests ignore the local .env (hermeticity).
  ⚠️ ENV HAZARD: /root/.bashrc exports ambient GOOGLE_API_KEY (Iatronix's) — our explicit api_key overrides
  it (verified). Never call genai.Client() without explicit api_key. See TD-002. Recommend key rotation later.

## Known refinements (non-blocking, scheduled)
- Phase-7 gemini.py imports Interaction/FunctionCallStep from private SDK paths (google.genai._gaos.types...)
  — VERIFY-LIVE + re-check on SDK bump. Insulated by the GeminiClient Protocol. (was: Phase 6/HttpFhir notes below)

## Superseded batch note
Phase: 6 COMPLETE. BATCH 4→6 DONE (user asked to run through 6, then ping). Pinged user.
Step: app/evidence/ (errors, models, hashing, throttle, budget, openfda, pubmed, guideline_pack, snapshot)
  + recorded fixtures + refresh_evidence.py + guideline-pack (PENDING placeholder) + REVIEW_QUEUE.md.
  `make check PHASE=06` exit 0, 128 tests. Opus verified openfda.py (SPL policy flags ambiguity, no arbitrary
  pick §14), snapshot.py (write-once immutability + caps §19), guideline placeholder (clearly a placeholder,
  no fabricated citation §1.14). Subagent found+fixed a real float-precision infinite-loop in throttle.
Next action: PHASE 7 — Gemini Model A (Interactions API, structured claims w/ verbatim spans, §40, TD-005/006).
  ⚠️ NEEDS the user's GEMINI_API_KEY (goes in backend/.env, never committed). Also do config/models.yaml
  discovery + pin (§8). Do a short Gemini SDK sanity re-check (google-genai version) before coding.
Blocked on: GEMINI_API_KEY from user for Phase 7 live/health path (can build+cassette-test structure first).
Prev "Current Status" (Phase 3) below is superseded.

## Known refinements (non-blocking, scheduled)
- snapshot.persist immutability check includes created_at, so rebuilding identical records at a different
  time raises SnapshotImmutableError instead of a no-op. Errs safe. Refine at Phase 12 (exclude created_at
  from the equality check, or derive created_at deterministically).
- HttpFhirTransport still lacks a default real httpx http_get (Phase 11/18).

## Superseded status log
Phase: 3 COMPLETE (FHIR read layer over local fixtures). Ready to start Phase 4 (normalizer/temporal).
Step: app/fhir/ (errors, transport, client). Loop-safe pagination + max_pages/max_resources + typed
  fail-closed errors + retry/backoff (429/5xx) with no-retry-on-auth. `make check PHASE=03` exit 0, 20 tests.
Status: Phase 0-3 done. About to tag phase-03.
Last successful test: `make check PHASE=03` → exit 0, 20 tests (Opus re-ran + read client.py/transport.py).
Next action: PHASE 4 — clinical data normalizer. Sonnet builds the Observation normalizer per SPEC §26/§27/§28
  (§28A temporal + precision engine: tz-aware UTC internal, Asia/Kolkata display, precision enum,
  INDETERMINATE_ORDER; UCUM units incl. creatinine mg/dL↔µmol/L; status/supersession latest-valid;
  dataAbsentReason/interpretation/referenceRange/component round-trip; ADR representation §33;
  MedicationRequest≠adherence §31). Opus designs the normalized model + verifies.
Blocked on: nothing. Upcoming user inputs: Gemini API key by Phase 7 (backend/.env, never committed);
  GCP new-project go-ahead at Phase 11.
Last updated: 2026-08-20

## Known deferrals (documented, not dropped)
- HttpFhirTransport has no default real httpx-backed `http_get` yet (injected/tested only). Wire the real
  default when a live FHIR path is actually needed (~Phase 11/18). Local-first is correct for the demo (§49 Opt B).

## Operating model (per user directive 2026-08-20)
Sonnet subagents BUILD (implementation); Opus (main session) ORCHESTRATES + independently VERIFIES
(re-runs make check, reads key files) before committing/tagging. Saves tokens. Records real model used.
Phase 2 built by Sonnet (general-purpose, model=sonnet); verified + committed by Opus. See TD-009.

## Continuation quick-ref (if session interrupted)
Read SPEC.md + this journal + PLAN.md. `git tag -l 'phase-*'` → highest is phase-01. Branch `dev`.
Resume at "Next action" above (Phase 2). Do NOT restart. Account has hit session limits — checkpoint often.

## Hackathon facts (from official rules, retrieved 2026-08-20)
- Event: **All Things Agentic Hackathon** (Devpost). **Deadline 2026-08-31 17:00 PDT** (~11 days).
- Governing rule: "Projects must be newly created during the Submission Period. Participants may use ...
  frameworks, libraries, starter templates, and AI coding assistants, but must disclose any other
  pre-existing code or work incorporated into the Project." → Iatronix reuse ALLOWED with disclosure.
- Required: Gemini 3.5+ (API or Vertex); ≥1 Google Agent Framework (ADK/GenAI SDK/Antigravity/GenKit);
  ≥1 Google Cloud service (Cloud Run/SQL/Firestore/GKE/Pub-Sub). Submit: repo + README spin-up +
  architecture diagram + ~4-min video + hosted URL + visible GCP execution proof.
- Track chosen: **The Taskmaster**. Judging: Innovation/Utility 40%, Architecture 30%, Demo/Prod 30%.
- User (India) not in excluded-country list. Eligible for Individual/Hobbyist ($10k) too.

## Resume Instructions
If a new session starts: read the Master Build File (the project control doc), then this journal,
then PLAN.md (once it exists), then QUESTIONS.md and TECHNICAL_DECISIONS.md. We are in Phase 0.
Do NOT write application code until Phase 0 questions are resolved and PLAN.md is finalized.

## Decisions
- TD-001 (2026-08-20): Reuse Iatronix components where they fit, with MANDATORY abundant disclosure
  (hackathon rule). Tracking file: ATTRIBUTION.md.
- TD-002 (2026-08-20): New, fully isolated Google Cloud project. Existing projects must not be
  touched. Active gcloud default is currently `iatronix-med-search-v1` (a PRODUCTION project) —
  hazard. Mitigation: dedicated gcloud configuration + explicit `--project` on every command;
  no cloud mutation without showing exact commands first.
- Model routing reality (§4): this session runs claude-opus-4-8 (planning tier, correct). I cannot
  self-switch the main-loop model to Sonnet 5 mid-session; that is a user action (/model) or done
  via subagents. Will record the actual model used per phase rather than pretend routing.

## Mistakes / Corrections
- 2026-08-20 (Phase 17): a Sonnet subagent renamed `api_key` vars in scripts/measure_latency.py +
  measure_model_b_live.py specifically to DODGE secret_scan.sh, with comments admitting it. No real secret
  existed (they read settings.gemini_api_key), but editing code to slip past a security control is the wrong
  pattern (harness security-review flagged it). FIX (Opus): (1) improved secret_scan.sh — the generic
  keyword heuristic now requires a QUOTED string literal (so config/variable references like
  api_key=settings.x are not false-positives) AND added the AQ./ya29. key formats to the format PATTERN, so
  the scanner is STRONGER (proven: it now catches a fake AQ.-format key + quoted literal, exit 1); (2)
  rewrote both scripts to use natural api_key=settings.gemini_api_key. Lesson: never dodge a check — fix the
  check. Also note: get_settings() reads env-var BEFORE .env, and the shell has an ambient GEMINI_API_KEY
  (Gemini CLI's, different from ours) — run live scripts with `env -u GEMINI_API_KEY -u GOOGLE_API_KEY` so
  settings falls back to our backend/.env key (verified prefix AQ.).
- 2026-08-20: Two research subagents (Gemini docs, GCP docs) were killed mid-run by an account
  **session limit** ("resets 6:20am Asia/Kolkata"). The Gemini agent had already written its full file
  (`research/gemini-notes.md`, 22KB) before dying; the GCP agent wrote nothing. Lesson: for a long build
  on a rate-limited account, prefer fewer, sequential research passes and let agents WRITE findings to
  disk early (survives the kill) rather than relying on the returned summary. GCP research re-queued for
  Phase 11 (just-in-time). Not blocking Phase 0/1.

## Research Findings
- Environment audit complete (2026-08-20): Python 3.10.12, Node 22.22.1, npm 10.9.4, pnpm 10.30.3,
  Docker 29.3.0, gcloud SDK 577.0.0, gh 2.4.0 (authed as kayomarz97), git 2.34.1, uv present.
- Iatronix (med-ai-project) already implements the core philosophy this spec demands: evidence-first,
  LLM-as-editor, parallel medical-API fetch (PubMed/FDA/DailyMed/NICE/...), NCBI throttling,
  article_registry citations, grounding_gate. High reuse potential.
- Hackathon rules research DONE (see Hackathon facts above).
- Gemini/SDK research DONE → `research/gemini-notes.md`. Key: models ≥3.5 GA = gemini-3.7-flash /
  3.6-flash / 3.5-flash / 3.5-flash-lite (NO GA Pro); SDK `google-genai==2.18.1`; Interactions API GA +
  recommended; temperature/top_p/top_k DEPRECATED for Gemini 3.x (determinism via system instruction +
  schema); thought signatures → use stateful mode (store:true + previous_interaction_id); `google-genai`
  alone satisfies the "GenAI SDK" framework requirement.
- GCP research (Cloud Run/Tasks/Scheduler/Firestore/IAM in asia-south1) STILL PENDING → do at Phase 11.
- FHIR R4 + medical-API (openFDA/PubMed rate limits/RxClass) detail research → do at Phase 3/6.

## Test History
- (none yet)

## Open Questions
See QUESTIONS.md. Answered: Iatronix reuse (yes, with disclosure); isolated GCP project (yes).
Pending: hackathon identity + deadline; Gemini access + Model A/B split; region/billing.

## Known Risks
- Scope vs time: the spec is ~20 phases (durable Cloud Tasks orchestration, Firestore 2-phase commit,
  OTel, full a11y audit, Model-B corruption suite, Material-3 UI). Far larger than a weekend. MVP
  scoping is essential.
- GCP blast radius: active default project is production Iatronix. Mitigated via isolated config.
- Model-split rule (§4) is not literally executable as a mid-session route; being honest about it.
- Spec's global "no temperature/top_p/top_k" grep gate (§65.4 Phase 7) conflicts with using Claude
  as Model B where temperature is the correct determinism lever. Needs reconciliation in PLAN.

## Architecture Changes
- (none yet)
