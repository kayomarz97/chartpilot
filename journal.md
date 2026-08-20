# Project Journal — doctor_helper (Pre-Clinic Chart-Prep Agent)

## Current Status
Phase: 1 COMPLETE (tagged phase-00, phase-01). Ready to start Phase 2.
Step: Repo live at github.com/kayomarz97/chartpilot (private); on branch `dev`; recovery tags pushed.
Status: Phase 0+1 done; no application code yet (correct). Clean checkpoint at commit 29ba538.
Last successful test: n/a (make check begins Phase 2)
Next action: PHASE 2 — backend skeleton. Create backend/ (Python 3.11 + FastAPI), pyproject with pinned
  deps, `GET /health` (200 only when required config present; non-200 otherwise), env-only config (no
  hardcoded project/model/URL), Makefile `make check` (ruff format --check, ruff, mypy, pytest, secret-scan),
  first unit test, evidence/phase_02.txt, tag phase-02. Run verifier before claiming done.
Blocked on: nothing. Upcoming user inputs: Gemini API key needed by Phase 7 (goes in backend/.env, never
  committed); GCP new-project creation needs user go-ahead on exact commands at Phase 11.
Last updated: 2026-08-20

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
