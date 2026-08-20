# RESEARCH.md — doctor_helper

This file has two parts:
- **Part A — Flaws found in the supplied specification** (required by §83 Step E). Done 2026-08-20.
- **Part B — External documentation research** (Gemini, GCP, FHIR, medical APIs, hackathon). PENDING —
  runs after project direction is confirmed, to avoid researching a path we won't take.

---

## Part A — Flaws found in the supplied specification (2026-08-20)

The Master Build File is unusually rigorous. These are genuine tensions/gaps to resolve, not nitpicks.

1. **The model split (§4) is not literally executable as a mid-session route.**
   The file wants Opus 4.8 for planning and Sonnet 5 for implementation and demands I "verify Claude
   Code actually routes to the requested model." In Claude Code the main-loop model is chosen by the
   user, not switched by me mid-turn. I can run subagents, but a "Sonnet 5" route isn't guaranteed.
   *Resolution:* be honest (the spec's own §4 demands this) — record the actual model used per phase;
   user drives the main model; use subagents/overrides where possible. Do not pretend routing occurred.

2. **The global "no temperature/top_p/top_k" grep gate (§11, enforced in §65.4 Phase 7) collides with
   using a non-Gemini Model B.** The no-sampling rule is a *Gemini 3.x* guidance. If Model B is Claude
   (the natural cross-vendor choice given the user's stack), setting `temperature=0` is the *correct*
   determinism lever and a blanket grep-fail would wrongly break it. *Resolution:* scope the grep gate
   to the Gemini client module only, not the whole repo; document per-provider determinism policy.

3. **Scope vs time.** ~20 phases including durable Cloud Tasks orchestration, Firestore two-phase
   commit, OpenTelemetry, immutable evidence snapshots, a Model-B corruption suite with an 80% release
   gate, and a full Material-3 accessible UI. This is weeks, not a hackathon weekend. *Resolution:*
   define an MVP vertical slice (see PLAN.md once written); the spec's own §50 (precomputed run + one
   live patient) implies a narrow judged demo. Defer heavy durability to "if time," documented.

4. **Model B identity under single-vendor blinding (§21.4).** The spec prefers a different vendor for
   Model B "where practical." With a Gemini-primary design and the user's existing Claude access, the
   natural, genuinely-independent choice is **Gemini = Model A, Claude = Model B**. This is a strength
   to design in deliberately, and it interacts with flaw #2 above.

5. **§49 Cloud Healthcare API is heavy for a demo.** Option B (local/static FHIR fixtures + a documented
   GCP-native path) is far lower demo-risk. *Recommendation:* Option B for the judged demo, with the
   Cloud Healthcare path documented and, if time allows, wired for the GCP-native story.

6. **Interactions-API assumption (§9).** The file repeatedly leans on "Gemini Interactions API is GA and
   recommended," but also (correctly) says to make the final call in Phase 0. This is post my training
   knowledge and must be verified. For stateless Cloud Tasks workers, application-owned durable state
   (§45) is the safer backbone regardless of which API is chosen. *Research item for Part B.*

7. **RxNav DDI (§15).** The spec correctly forbids the discontinued NLM RxNav drug-drug-interaction API.
   RxClass (class membership) and RxNorm (normalization) status still need live verification. *Part B.*

8. **openFDA label selection (§14).** Sound policy, but real-world SPL metadata is messy; "prefer
   reference-listed/NDA over ANDA" is not always determinable from returned fields. Must fail to a review
   flag (spec already says so) — flag as an implementation-risk, not a spec flaw.

9. **Determinism claims are version-specific and dated.** §11 asserts top_p/top_k are deprecated for
   Gemini 3.x. Verify against current docs; if wrong, the whole no-sampling posture needs revisiting.

10. **Environment parity.** Local Python is 3.10.12; Iatronix uses 3.11 (and `tomllib` needs 3.11).
    *Recommendation:* pin 3.11 for the backend to match Iatronix and avoid version-specific surprises.

11. **§22.3 release gate (80% Set M, ≤1 false-accept) as a ship blocker.** Excellent discipline, but may
    be unmet in hackathon time. The spec's honest fallback (withhold the "independent review ✓" badge,
    show ADVISORY, record the numbers) is the right behavior — plan to use it if needed, not to fake it.

12. **Reuse-disclosure obligation is now a hard requirement** (user: hackathon rule). Any reused Iatronix
    code must be flagged everywhere (README, ATTRIBUTION.md, per-file headers, UI credit). Tracked in
    ATTRIBUTION.md. This is additive to the spec, not a flaw in it.

### Net assessment
The spec is safe-by-design and mostly internally consistent. The two changes worth making before build:
(a) scope the sampling-param gate per-provider (flaw #2), and (b) commit to an explicit MVP slice with the
heavy GCP durability deferred and documented (flaw #3). Everything else is verify-in-Part-B or a known risk.

---

## Part B — External documentation research

### DONE (2026-08-20)
- **Hackathon rules** — All Things Agentic (Devpost). Deadline 2026-08-31 17:00 PDT. Newly-created +
  reuse-disclosure rule; Gemini 3.5+ / Google Agent Framework / ≥1 GCP service required; Taskmaster track.
  (Full facts in journal.md "Hackathon facts".)
- **Gemini API / google-genai SDK** — full notes in `research/gemini-notes.md` (verified vs official docs,
  retrieved 2026-08-20). Feeds TD-003, TD-005, TD-006, TD-007.

### PENDING (do just-in-time at the relevant phase, official sources only)
- **GCP durable stack** (Phase 11): Cloud Run timeouts/auth; Cloud Tasks queue + OIDC + retry/dead-letter +
  idempotency; Cloud Scheduler cron (Asia/Kolkata); Firestore Native + transaction/batch op limit;
  IAM least-privilege SAs; asia-south1 gaps (esp. whether Gemini must be called from another region).
- **FHIR R4 detail** (Phase 3): Observation value[x]/component/status/referenceRange; Bundle pagination.
- **Medical data APIs** (Phase 6): openFDA label API + rate limits + SPL fields; PubMed E-utilities rate
  limits + API key params; RxClass current status; DailyMed (deferred).

### Superseded / no longer needed
- ~~Gemini API research after direction confirmed~~ → DONE above.
- GCP: Cloud Run request/timeout limits; Cloud Tasks; Cloud Scheduler; Firestore transaction limits;
  Cloud Healthcare API FHIR store basics; IAM least-privilege for Scheduler→enqueue→worker.
- FHIR R4: Observation value[x]/component/status/referenceRange; Appointment; Bundle pagination.
- Medical data: openFDA drug label API + rate limits; PubMed E-utilities + rate limits + API key;
  RxNorm/RxNav + RxClass current status; DailyMed SPL.
- Hackathon: exact rules, tracks (Taskmaster), reuse-disclosure rule text, deadline, judging rubric.
