
# Phase 0 Plan — Research, Audit, Questions

**Date:** 2026-08-20
**Project:** doctor_helper (Pre-Clinic Chart-Prep Agent) — part of the Iatronix ecosystem
**Model in use this session:** claude-opus-4-8 (planning tier per Master Build File §4)

## Goal of Phase 0 (no application code)
Per Master Build File §5, §64 (Phase 0), §83:
1. Inspect workspace + environment — **DONE**
2. Inspect user's claude-master repo (conventions) — **DONE (structure reviewed)**
3. Research current official docs — **PENDING** (Gemini API, GCP, FHIR, openFDA, PubMed, RxNorm/RxClass, hackathon rules)
4. Audit the specification itself — **DONE (RESEARCH.md Part A)**
5. Create Phase 0 docs — **IN PROGRESS**
6. Ask material questions — **IN PROGRESS**
7. Finalize PLAN.md after answers — **PENDING**
8. Begin Phase 1 — **PENDING**

## Locked decisions (from user, 2026-08-20)
- **TD-001** Reuse Iatronix components where they fit — WITH mandatory, abundant disclosure everywhere (hackathon rule). See ATTRIBUTION.md.
- **TD-002** Brand-new, fully isolated Google Cloud project. Existing projects (`iatronix-med-search-v1`, `gen-lang-client-0221156184`) must NOT be affected. Active default is currently `iatronix-med-search-v1` — DANGER. Use a dedicated gcloud config + explicit `--project` always.

## Approach
- Answer the remaining material questions (hackathon identity + deadline; Gemini access + Model A/B split; region/billing) before finalizing scope.
- Do targeted external research (docs-researcher) ONLY after direction is confirmed, to avoid wasted tokens.
- Propose an MVP vertical slice for the judged demo; defer heavy GCP durability to "if time."

## Next action
Ask the 3 remaining material questions, then run external documentation research.
