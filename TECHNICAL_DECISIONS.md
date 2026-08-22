# TECHNICAL_DECISIONS.md — doctor_helper

Append-only log of material technical decisions. Each: ID, date, decision, rationale, consequences.

---

## TD-001 — Reuse Iatronix components, with mandatory abundant disclosure
**Date:** 2026-08-20 · **Status:** LOCKED (user directive)

**Decision:** Where an Iatronix component fits (evidence adapters, NCBI/openFDA throttling patterns,
grounding-gate philosophy, citation registry ideas), reuse it rather than rebuild. Every reuse MUST be
disclosed prominently because the hackathon requires disclosure of reused/existing work.

**Disclosure surface (all required):**
- `README.md` — top-level "Reused from Iatronix" section.
- `ATTRIBUTION.md` — authoritative per-component provenance list.
- Per-file header on any file copied/adapted from Iatronix (source path + commit + what changed).
- `journal.md` decisions log.
- **Visible UI credit** (e.g. an "Attribution" entry in the app footer/about).

**Consequences:** Adds a provenance-tracking obligation to every reuse. A reused file without a header is
a defect. Never present reused work as original.

---

## TD-002 — Brand-new, fully isolated Google Cloud project; existing projects untouchable
**Date:** 2026-08-20 · **Status:** LOCKED (user directive)

**Decision:** doctor_helper gets its own new GCP project, isolated from all existing projects. Existing
projects — `iatronix-med-search-v1` (Iatronix-Med-Search, **currently the active gcloud default**) and
`gen-lang-client-0221156184` (Iatronix / AI Studio) — must not be affected in any way.

**Guardrails (mandatory):**
- Create and use a dedicated gcloud *configuration* for doctor_helper so the Iatronix default is never
  the active context during this work.
- Every `gcloud` command carries an explicit `--project=<new-id>`; never rely on the active default.
- No cloud-resource creation/mutation without showing the user the exact commands first.
- New, isolated Gemini API key under the new project — do NOT reuse the Iatronix AI Studio key/quota.

**Consequences:** Slightly more ceremony per command; total isolation of billing, quota, IAM, and data.

**Environmental hazard found (2026-08-20):** the VPS `/root/.bashrc` globally exports the user's other
API keys — including `GOOGLE_API_KEY` (an `AIza…` key, Iatronix's) and an ambient `GEMINI_API_KEY`.
`google-genai` auto-reads `GOOGLE_API_KEY` from the environment, so a naive `genai.Client()` locally would
use Iatronix's key/quota — an isolation breach. Mitigation (verified live): our `app/agent/gemini.py`
always constructs `genai.Client(api_key=settings.gemini_api_key)` with the EXPLICIT key, and a live test
confirmed the explicit key overrides the ambient `GOOGLE_API_KEY` (bogus ambient key + explicit our-key →
success). Cloud Run has no `.bashrc`, so production is unaffected. Rule: never call `genai.Client()`
without an explicit `api_key`; never set `GOOGLE_API_KEY` in our app's environment.

**Live key note:** the user's Gemini key uses the newer `AQ.…` format (len 53), not the classic `AIza…`.
It authenticates fine (`models.list()` returns both pinned models). Key is in gitignored `backend/.env`.
Recommend rotating it after the build since it was pasted into the session transcript.

---

## TD-003 — Model A and Model B are BOTH Gemini (hackathon rule); different model IDs for partial independence
**Date:** 2026-08-20 · **Status:** LOCKED (user directive: "use gemini as second and first model as per
hackathon rules"; hackathon requires Gemini 3.5+).

**Decision:** Model A (primary reasoning) = `gemini-3.7-flash`; Model B (adversarial reviewer) =
`gemini-3.5-flash`. Both GA/stable, ≥3.5, discovered via `client.models.list()` and pinned in
`config/models.yaml` (§8). Using two DIFFERENT Gemini models gives a degree of independence.

**Limitation (disclosed per §21.4, in README + here):** both models are the same vendor (Google). This is
weaker than cross-vendor blinding. Compensate with stronger deterministic gates (§16–18) and the §22
corruption suite; report Set D/M metrics honestly; withhold the "independent review ✓" badge if §22.3
threshold unmet (show ADVISORY). Earlier proposal of Claude-as-Model-B is OFF (hackathon mandates Gemini).

**Consequence for RESEARCH.md flaw #2:** since both models are Gemini and Gemini 3.x deprecates
temperature/top_p/top_k entirely, the "no sampling params" posture applies to ALL model calls — no
per-vendor exception needed. Determinism via fixed system instructions + response schemas (verified:
`research/gemini-notes.md` §5).

---

## TD-005 — Gemini API surface = Interactions API, stateful mode
**Date:** 2026-08-20 · **Status:** LOCKED (verified `research/gemini-notes.md` §2–4; implemented Phase 7)

**Decision (the §9 API choice):** use the **Interactions API** (`client.interactions.create(...)`) over the
legacy `generate_content` surface. Alternatives evaluated per §9:
- *generate_content*: still supported, but Google now leads its own structured-output + function-calling
  guides with Interactions; would mean owning thought-signature replay ourselves (§10) — more fragile.
- *Interactions API (chosen)*: GA + recommended; native structured output (`response_format` w/ Pydantic
  JSON schema); native tool orchestration; **stateful mode** (`store:true` + `previous_interaction_id`)
  keeps thought signatures server-side — ideal for our **stateless Cloud Tasks workers** (§45): we persist
  only the `previous_interaction_id` in our own durable state and never serialize opaque signature blobs.
- *ADK / GenKit / Antigravity*: heavier agent runtimes that would fight our own Cloud Tasks state machine
  (see TD-007); not adopted.

**State ownership (§9):** application owns durable state (`run_id + patient_id` checkpoint, §45); the Gemini
interaction is re-associated by storing its `interaction_id` alongside that checkpoint. Server-side
interaction state is NOT used as a substitute for our durable state.

**Implementation (Phase 7):** structured output via `response_format={type,mime_type,schema=...model_json_schema()}`;
function-result steps must match `call_id`/`name`/count of the preceding function_call steps exactly (Gemini
3.x strict matching) — enforced locally in `toolcall.assert_function_results_match` + regression-tested (§10).

**Known fragility (flagged, Phase 7):** the real `app/agent/gemini.py` adapter currently imports
`Interaction`/`FunctionCallStep` from internal SDK submodule paths (`google.genai._gaos.types...`) to dodge a
static-analysis ambiguity, and has `# VERIFY-LIVE:` flags (e.g. whether `Model.name` is bare vs
`models/`-prefixed). These must be re-verified against the live SDK when `GEMINI_API_KEY` is available, and
on any `google-genai` version bump. Our pipeline is insulated from these by the `GeminiClient` Protocol.

## TD-006 — SDK pin: google-genai==2.18.1
**Date:** 2026-08-20 · **Status:** LOCKED (re-verify on PyPI before demo day; SDK ships frequently)
Access via Gemini Developer API with `GEMINI_API_KEY` (user supplies per hackathon). Vertex/Enterprise mode
available later via `genai.Client(enterprise=True, project, location)` (note: kwarg is now `enterprise=True`,
NOT `vertexai=True`). Sampling-param grep gate (§65.4 Phase 7) asserts temperature/top_p/top_k ABSENT from
the Gemini client module.

## TD-007 — Agent framework = google-genai (satisfies "GenAI SDK" requirement); ADK not adopted
**Date:** 2026-08-20 · **Status:** LOCKED
`google-genai` is officially the "Google Gen AI SDK" and is a listed qualifying framework. We own
orchestration via Cloud Tasks + app state; adopting ADK would fight our own state machine. Interpretation
of the rule, flagged as such; if the hackathon committee reads it more strictly, revisit.

## TD-008 — Working repo name: `chartpilot` (private GitHub repo)
**Date:** 2026-08-20 · **Status:** LOCKED (§74 — I choose the name; not reusing an existing exact name;
"-Pilot" echoes the user's WristPilot style). Local folder stays `doctor_helper`; product/repo = ChartPilot.

---

## TD-004 (proposed) — FHIR backend = local fixtures for demo, Cloud Healthcare path documented
**Date:** 2026-08-20 · **Status:** PROPOSED (§49 Option B)
Rationale: lowest demo risk; GCP-native Cloud Healthcare path documented and wired if time permits.

---

## TD-009 — Operating model: Sonnet subagents build, Opus verifies
**Date:** 2026-08-20 · **Status:** LOCKED (user directive)
Implementation is delegated to Sonnet subagents (Agent tool, `model: sonnet`); the Opus main session
orchestrates, writes the brief, and INDEPENDENTLY verifies (re-runs `make check`, reads load-bearing files)
before committing + tagging. Rationale: save Opus tokens while keeping Opus as architect/verifier. Honors
SPEC §4 intent (Sonnet implements, Opus does architecture/verification) and logs the real model used per phase.
Subagents must NOT commit/tag/push — Opus does that after verification.

---

## TD-010 — Demo error-status patients: keep ONE as a labeled "safety demonstration"
Decision (user, 2026-08-21): the two error-status demo patients (FAILED, DEAD_LETTER) read as "the app is
broken" to a first-time viewer, but they exist to prove the fail-closed design (a failure surfaces loudly,
never as a silent "no findings"). Resolution: convert one to a rich SUCCESS case; keep ONE failure, rendered
inside an explicit "Safety demonstration — how failures surface" section so it is unmistakably an intentional
feature. Rationale: preserves the safety selling-point without looking buggy.

## TD-011 — "Make the backend visible" = wire the UI to REAL live backend data
Decision (user, 2026-08-21): add a PUBLIC, read-only backend endpoint `GET /runs/{run_id}` that returns the
persisted run results from Firestore (status + findings + timeline + lab trends), and make the Next.js
dashboard fetch and render it — so judges see the ACTUAL AI output from the live pipeline, not built-in mock
data. Plain: the website shows what the AI really produced. Technical: read-only endpoint (synthetic data, no
secrets, CORS) over the same Firestore the private worker writes; the write path stays private/OIDC. The UI
falls back to enriched authored demo data if the backend is unreachable, so it is never broken. The worker
persists a UI-shaped "presentation" payload at finalize so the read endpoint is a trivial Firestore read.

## TD-012 — Clinical guidelines via PubMed guideline-PUBLICATION-TYPE citations (not guideline text)
Decision (user, 2026-08-21), with a correction the user asked about: PubMed does NOT provide licensed
guideline TEXT — it indexes literature, INCLUDING citations to guideline publications (publication type
"Guideline"). So the honest, licensing-safe approach is to query E-utilities with `ptyp=Guideline` for the
patient's meds/conditions and surface REAL guideline CITATIONS (title, journal, year, PMID, link) as
GUIDELINE-tier evidence with `reviewed_by=PENDING`. Because the existing gate caps any PENDING guideline at
PARTIALLY_VERIFIED, these can never alone make a claim VERIFIED. We copy no guideline body text (licensing).
This replaces the clearly-labelled placeholder guideline record with real, dynamically-retrieved citations.

## TD-013 — Push to `main` (one-time override of the "user merges main" rule)
Decision (user, 2026-08-21): the user explicitly instructed pushing to `main`. This overrides the standing
global rule ("never push main directly; the user merges main") for this occasion only. Executed as a
fast-forward merge of `dev` into `main` + `git push origin main`, after `dev` is green and pushed. The default
(dev-only, user merges main) resumes afterward unless the user says otherwise.

## TD-014 — Self-improving loop: two feedback loops, a hard tier boundary, no self-tuning on the held-out eval
Decision (user, 2026-08-22): add a production-style self-improving loop on top of the existing pipeline,
built by Sonnet subagents with Opus verifying (TD-009). Two loops:
- **Inner loop (Phase A, `app/pipeline/runner.py` + `app/agent/revise.py`):** when Model A's
  `verbatim_supporting_span` fails SPAN_VERIFICATION, feed the DETERMINISTIC failure reason + the real
  source text back and let Model A re-quote, bounded by `max_revise_iterations` (default 2). A safety guard
  (`_revision_is_safe`) forbids any change to `claim_id`/`claim_type`/`statement`/`patient_evidence` and lets
  evidence sources be dropped but never added/switched — the loop repairs CITATIONS only, never clinical
  meaning. Model B + the fail-closed final gate stay authoritative; budget exhaustion or any exception keeps
  the failing verdict (never a silent "no findings").
- **Outer loop (Phase C, `app/improve/`):** collect the persisted signals (automated gate/Model-B outcomes +
  the Phase B clinician CONFIRM/OVERRIDE/CORRECT labels) → propose ONE change to an AUTO-tier target → prove
  it beats the frozen benchmark on a HELD-OUT slice → canary → promote to a versioned ledger. Exposed as
  OIDC-only `POST /improve-run`.

The three-tier boundary (the reason this is safe to ship in a clinical context):
| Tier | Targets | Who may change it |
|---|---|---|
| **AUTO** | `MODEL_A_PROMPT`, `EVIDENCE_RANKING` | the loop, IF a candidate beats the frozen benchmark with zero regression |
| **HUMAN-GATED** | Model-B threshold, execution budgets | the loop proposes a diff; a human approves |
| **FROZEN** | clinical rules (`K_HIGH_RISK_001`), validity math (eGFR/CKD-EPI), the fail-closed gate, normalization | the loop may DRAFT, never self-apply — `assert_target_allowed` is default-deny and refuses these |

Two invariants make it honest: **(1) determinism is preserved** — prompts stay pinned Python constants; the
loop writes versioned artifacts to a ledger and a resolver returns the active version or the pinned default
(empty ledger ⇒ byte-identical to today; live consumption is deliberately opt-in, `run_patient` unchanged).
**(2) No training on the held-out eval** — the §22 corruption suite is the frozen benchmark (never mutated by
the loop) and clinician cases split deterministically into train (propose) vs holdout (evaluate). This
directly avoids the trap the README already calls out (Model B measured at 75% false-reject: a loop that
self-tuned against its own suite would just game the number). Honest scope: the default LLM-backed proposer is
a clearly-marked no-op placeholder and the default hermetic score_fn can't vary with candidate text, so the
stock loop always fail-closed rejects — the machinery is complete + tested; the live proposer is future wiring
(needs real accumulated clinician data + a `docs-researcher` pass), not a fabricated live call.
