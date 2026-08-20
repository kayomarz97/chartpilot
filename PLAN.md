# PLAN.md — doctor_helper (working name "ChartPilot")

**Status:** FINALIZED for build (Phase 0 complete). Supersedes ad-hoc scope notes; governed by `SPEC.md`.
**Owner:** kayomarz97 (physician-founder). **Builder:** Claude Code.
**Deadline:** 2026-08-31 17:00 PDT (All Things Agentic Hackathon). ~11 days from 2026-08-20.
**Track:** The Taskmaster (also eligible: Individual/Hobbyist $10k, Best Architectural Design).

---

## 1. What we are building (plain, then technical)
**Plain:** An autonomous "night-before-clinic" assistant. For each patient on tomorrow's list, it reads
their record, works through it step by step, and prepares a short safety-focused briefing that flags
things a doctor could miss in a fast chart review — e.g. a high potassium in someone on a drug that
raises potassium — and it *shows its evidence* for every flag, with an independent second AI trying to
disprove each flag before it's shown.

**Technical:** A durable, event-driven FHIR chart-prep agent. Deterministic layer owns patient facts;
Gemini provides longitudinal synthesis; every external claim carries a verbatim, deterministically
verified citation; a blinded second Gemini model adversarially reviews each claim; a final safety gate
fails closed. Orchestrated with Cloud Scheduler → Cloud Run → Cloud Tasks → Firestore. Per `SPEC.md §85`.

## 2. Hackathon fit (why this scores)
- **Innovation & Utility (40%):** autonomous, high-value *action* (a prepared brief), not a chatbot.
- **Architecture (30%):** decoupled deterministic/AI/evidence layers, durable state machine, idempotent
  Cloud Tasks, fail-closed safety gate, immutable evidence snapshots.
- **Demo & Production (30%):** deployed on GCP (visible execution), precomputed multi-patient run + one
  live ≤90s patient, polished evidence drawer, architecture diagram, ~4-min video.

## 3. Required-tech compliance (hard rules)
- ✅ **Gemini 3.5+**: Model A `gemini-3.7-flash`, Model B `gemini-3.5-flash` (discovered + pinned, §8).
- ✅ **Google Agent Framework**: `google-genai` (Google Gen AI SDK) — satisfies "GenAI SDK" branch.
- ✅ **Google Cloud service(s)**: Cloud Run + Cloud Tasks + Cloud Scheduler + Firestore (asia-south1).
- ✅ **Newly created during period + reuse disclosed**: predominantly new code; Iatronix reuse disclosed
  everywhere (ATTRIBUTION.md, per-file headers, README, UI credit). Repo created Aug 2026.

## 4. Reuse vs greenfield (TD-001)
- **Reuse from Iatronix (each disclosed):** NCBI/openFDA throttling *patterns*, evidence-first design
  philosophy, grounding-gate concept, citation-registry concept. Prefer reusing *patterns/knowledge*;
  copy code only where it clearly accelerates, with a provenance header + ATTRIBUTION.md row.
- **New to ChartPilot:** FHIR R4 normalization + temporal/precision engine, ClinicalValidityEngine,
  deterministic clinical rules, verbatim-span citation verifier, blinded Model-B adversarial harness +
  corruption suite, immutable evidence snapshots, Cloud Tasks durable orchestration + two-phase Firestore
  finalization, the entire UI. This is the bulk of the work and keeps us clearly on the "newly created" side.

## 5. MVP scope (ruthlessly narrowed for 11 days)
**IN (the judged vertical slice):**
- Local FHIR R4 fixtures (§49 Option B) — Patients A (high-K), B (resolved), C (ambiguous); D (prior ADR) if time.
- FHIR normalization: Observation status/value[x]/units(UCUM)/referenceRange/interpretation/component;
  temporal + date-precision engine (§28A); ADR representation (§33); MedicationRequest≠adherence (§31).
- ClinicalValidityEngine (§30) + two registered domains: `K_HIGH_RISK_001` (§35) and eGFR validity (§30)
  — proves the framework is general (§67.21), not a one-off.
- Evidence: openFDA drug-label adapter (§14 SPL policy) + PubMed E-utilities cache (§12A) + a tiny
  curated guideline pack (≤5 records, all `reviewed_by: PENDING`) + immutable snapshots (§19).
- Gemini Model A structured claims w/ verbatim spans (§40) → deterministic citation verifier gates 1–4
  (§16–18) → Gemini Model B blinded adversarial review (§21) → final safety gate (§10 spec) → verdicts.
- Durable orchestration: Scheduler → /enqueue-run → Cloud Tasks → /tasks/process-patient → Firestore
  (subcollections §44, two-phase finalize §45A, idempotent §46), deployed to Cloud Run.
- Frontend: dark Material-3 dashboard + **evidence drawer (showpiece §58)** + longitudinal timeline (§59).
- Adversarial: injection invariant (§53), fabricated resource/value/citation, Model-B corruption Set D/M (§22).
- Hermetic tests (§23) with recorded Gemini cassettes; `make check` gates per phase (§65).
- Deliverables: README (honesty §79 + disclosure), architecture diagram, ~4-min demo video, hosted URL.

**DEFERRED (documented, not silently dropped — SPEC §1.12):**
- Cloud Healthcare API (use local fixtures; GCP-native path documented) — §49 Option B.
- DailyMed adapter (openFDA covers label needs), RxClass live API (use versioned class-mapping artifact §15).
- OpenTelemetry/Cloud Trace full spans (basic structured logging + minimal timing; add spans if time §71).
- Full WCAG audit tooling beyond core (do: axe pass on 3 views, greyscale check, keyboard, reduced-motion §57A).
- Synthea ingestion, ADK/GenKit/Antigravity, multi-jurisdiction labels, Patient E.

## 6. Architecture (target)
```
Cloud Scheduler (nightly, Asia/Kolkata)
  └─> Cloud Run  POST /enqueue-run   (auth: OIDC)         → creates run_id, lists tomorrow's Appointments
        └─> Cloud Tasks queue (retry + dead-letter)
              └─> Cloud Run POST /tasks/process-patient  (auth: OIDC, idempotent per run_id+patient_id)
                    → FHIR fixtures → normalize → rules → evidence(snapshot) → Model A
                    → citation verifier (deterministic gates) → Model B (blinded) → safety gate
                    → Firestore (subcollections, two-phase commit) → checkpoint each stage
Next.js UI  ← reads Firestore (compact summaries + drawer detail)
```
Backend: Python 3.11 + FastAPI + `google-genai`. Frontend: Next.js 15 / React. Persistence: Firestore
(Native). Region: asia-south1; **verify Gemini region availability in Phase 11 — may call Gemini via the
Developer API (global) while infra stays asia-south1** (GCP research pending).

## 7. Model configuration (config/models.yaml, discovered + pinned — §8)
- Model A (primary reasoning): `gemini-3.7-flash` (GA/stable).
- Model B (adversarial reviewer): `gemini-3.5-flash` (GA/stable) — different model → partial independence.
- **Limitation (disclosed §21.4):** both are Gemini (single vendor), mandated by hackathon rule. Compensate
  with stronger deterministic gates + the §22 corruption suite; report Set D/M metrics honestly.
- Interactions API, stateful mode (`store:true` + persisted `previous_interaction_id`). No temperature/top_p/top_k.
- Startup health-check calls `client.models.list()`; fail loud if a pinned ID is absent.

## 8. Evidence & disclosure
- Sources: openFDA (US FDA label), PubMed (literature-tier, never labelled "guideline" §12A.1), curated
  guideline pack (PENDING review → claims capped at PARTIALLY_VERIFIED §12). Caps: ≤15 guideline, ≤150 PubMed.
- Immutable snapshots; live demo serves evidence from cache (zero PubMed calls §12A.4).
- **Disclosure of Iatronix reuse:** ATTRIBUTION.md + per-file headers + README section + visible UI credit.

## 9. Phase plan & rough schedule (compressed; walking-skeleton-first)
Build a THIN end-to-end slice early (Patient A, mocked Gemini), then thicken each layer. Every phase ends
with `make check` → `evidence/phase_NN.txt` exit 0 → `phase-NN` tag (§65).
- **Aug 20 (today):** Phase 0 ✅, Phase 1 (repo, branches, PLAN final).
- **Aug 21–22:** Phase 2 backend skeleton; Phase 3 FHIR layer; Phase 4 temporal/units/status/ADR.
- **Aug 23–24:** Phase 5 ClinicalValidityEngine + K rule + eGFR; Phase 6 evidence + snapshots.
- **Aug 25–26:** Phase 7 Model A; Phase 8 citation verifier.
- **Aug 27:** Phase 9 Model B + corruption suite; Phase 10 safety gate.
- **Aug 28:** Phase 11 durable orchestration; Phase 12 Firestore.
- **Aug 29:** Phase 13 frontend + evidence drawer; Phase 14 demo fixtures.
- **Aug 30:** Phase 15 adversarial; Phase 16 hermetic; Phase 17 latency; Phase 18 deploy.
- **Aug 31:** Phase 19 smoke; Phase 20 self-audit; architecture diagram; ~4-min video; submit.

**Reality check:** this is aggressive for a solo timeline. If we slip, the priority order to protect is:
(1) a working, safe end-to-end slice on Patient A deployed to GCP with the evidence drawer;
(2) the adversarial/safety story (injection invariant + Model-B metrics);
(3) breadth (more patients/rules). We ship a smaller *correct* thing over a bigger broken one (§SPEC 6,7).

## 10. Risk register
- **Session/rate limits** (already hit once on research subagents): checkpoint often; keep durable journal.
- **GCP setup risk on a brand-new project** (billing/IAM/asia-south1 availability): TD-002 isolation; do
  Phase 11 GCP research before touching cloud; show all commands first.
- **Latency ≤90s**: cache evidence, bound model calls, measure early (§17).
- **Single-vendor Model B**: disclosed; compensate with deterministic gates + corruption suite.
- **Scope**: MVP is still large; walking-skeleton-first + documented deferrals mitigate.

## 11. Next action
Phase 1: local git init + Phase-0 commit → create **private** GitHub repo `chartpilot` (§74) → `dev` branch.
Then Phase 2 backend skeleton.
