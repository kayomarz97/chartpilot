# ATTRIBUTION.md — Reused & Prior Work Disclosure

> **Hackathon reuse disclosure.** This project reuses components and design patterns from the author's
> existing **Iatronix** platform (`github.com/kayomarz97/iatronix`, live at med.kayomarz.com). This is
> disclosed here, in `README.md`, in `journal.md`/`TECHNICAL_DECISIONS.md`, in per-file headers on every
> reused file, and visibly in the application UI. Nothing reused is presented as original work.

## What Iatronix is (context for judges)
Iatronix is an evidence-based medical reference engine: it fetches live data from authoritative medical
APIs in parallel, ranks by evidence quality, and uses an LLM only as an *editor* of retrieved evidence —
never as the source of facts. doctor_helper applies the same evidence-first philosophy to a different
problem (pre-clinic FHIR chart-prep) and reuses concrete building blocks where they fit.

## Reuse ledger
Every row here is also enforced by a header comment in the corresponding file.

| doctor_helper file/area | Reused from Iatronix | Nature of reuse | What changed |
|---|---|---|---|
| _(to be filled as reuse happens)_ | | | |

## Original to doctor_helper (NOT from Iatronix)
- _(to be filled: FHIR normalization layer, ClinicalValidityEngine, deterministic rules, Model-B
  adversarial harness, evidence snapshots, Cloud Tasks orchestration, the UI, etc.)_

## Third-party data sources & their standing
- _(openFDA, PubMed E-utilities, RxNorm/RxClass, DailyMed — filled during Phase 6, with license notes.)_
