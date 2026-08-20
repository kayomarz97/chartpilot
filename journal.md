# Project Journal — doctor_helper (Pre-Clinic Chart-Prep Agent)

## Current Status
Phase: 7 COMPLETE (Gemini Model A integration, hermetic). `make check PHASE=07` exit 0, 147 tests.
Step: app/agent/ (protocol, models=Claim schema §40, claims parse fail-closed, toolcall §10 strict-match,
  model_pin §8 loud-fail, prompts fixed system instruction, gemini.py real adapter). config/models.yaml
  pinned (A=3.7-flash, B=3.5-flash). New make-check gate: no_sampling_params. google-genai==2.18.1 +
  pyyaml added. Opus verified models.py/toolcall.py/check script; re-ran make check.
Next action: PHASE 8 — deterministic citation checker (Gates 1-4: source retrieval, content hash, verbatim
  SPAN verification w/ §17 normalization, metadata) over the evidence snapshot; model-emitted offsets
  rejected; absent span REJECT; ambiguous multi-match FLAG_FOR_REVIEW; changed-snapshot invalidation.
  Then Phase 9 (Model B), Phase 10 (safety gate). Continue via Sonnet subagents; Opus verifies.
⚠️ AWAITING from user: GEMINI_API_KEY (backend/.env, gitignored) to run the LIVE Model-A health check +
  resolve the Phase-7 VERIFY-LIVE flags (Model.name prefix; internal-submodule import; Interactions response
  mapping). Everything hermetic works without it.

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
