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
**Date:** 2026-08-20 · **Status:** LOCKED (verified `research/gemini-notes.md` §2–4)
Use `client.interactions.create(...)` (GA, recommended) over legacy `generate_content`. Structured output
via `response_format={type,mime_type,schema=Pydantic.model_json_schema()}`. Multi-turn tool calling uses
**stateful mode** (`store:true` + persist `previous_interaction_id` in Firestore) so Google's servers hold
thought-signature history — clean fit for stateless Cloud Tasks workers (§9/§10). Function-result steps
must match `id`/`name`/count of the preceding function_call steps exactly (Gemini 3.x strict matching) —
regression test required (§10).

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
