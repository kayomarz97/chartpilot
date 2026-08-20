# ChartPilot — Evaluation

This document reports the project's honest measurement results: real latency
against the live pipeline, the §22 Model B corruption-suite catch rate, and
what the demo patients are (and are not) evidence of. Phase 17
(`.claude/plans/`, see journal.md) built the instrumentation and the
hermetic/deterministic harnesses; the two LIVE measurement runs below are
executed separately (they cost real Gemini API tokens and are excluded from
`make check` by design) and their numbers are filled in once that live run
has actually happened.

## Single-patient latency

Measured by `scripts/measure_latency.py` (LIVE — real `GeminiInteractionsClient`
calls, Model A `gemini-3.7-flash` + Model B `gemini-3.5-flash`) against demo
Patient A, run N times end to end through `app.pipeline.runner.run_patient`
with per-stage timing (`stage_timings`, spec §50).

**LIVE RUNS — 2026-08-20/21.** Two measurement sessions gave very different results; BOTH are reported
honestly (§50: never fake live results).

Per-stage (clean session, n=3, 2026-08-21):

| Stage | p50 (s) | Worst (s) |
|---|---|---|
| fetching | 0.00 | 0.00 |
| normalizing | 0.00 | 0.00 |
| rules_evaluated | 0.00 | 0.00 |
| evidence_retrieval | 0.00 | 0.00 |
| **ai_reasoning (Model A)** | **151.84** | **163.48** |
| citation_check | 0.00 | 0.00 |
| **independent_review (Model B)** | **40.12** | **41.34** |
| final_validation | 0.00 | 0.00 |
| persisted | 0.00 | 0.00 |
| **TOTAL** | **189.23** | **193.18** |

- **Session A (2026-08-20, n=2 usable):** total **43.6 s** and **57.7 s** — both **≤ 90 s (MET)**. (A third run
  crashed on a transient Gemini `500 "high demand"` — the failure that prompted the retry/fail-closed fix.)
- **Session B (2026-08-21, n=3):** totals **189.2 / 193.2 / 124.8 s** — p50 **189.2 s**, **all > 90 s (NOT MET)**.

**Target:** total p50 ≤ 90 s. **Result: NOT reliably met.** The entire budget is dominated by the **Model A
`ai_reasoning` call (gemini-3.7-flash)**, which swung from a few seconds (Session A) to ~150 s (Session B) —
Gemini-3.7-flash serving latency varies enormously with server-side load (the same load that produced the
transient 500). Every deterministic stage is effectively free (~0 s); Model B adds a stable ~40 s.

**Optimization levers (recorded, not yet applied — would need live re-measurement):**
1. Set `thinking_level: "low"` / `"minimal"` on the Model A call (Gemini 3.x defaults to `medium` thinking;
   `research/gemini-notes.md §5`) — likely the single biggest win.
2. Use a faster Model A (`gemini-3.5-flash-lite`) and/or trim the Model A input (evidence regions are passed
   verbatim; they can be bounded).
3. **For the judged demo, the precomputed multi-patient run (`tests/fixtures/demo/precomputed_run.json`)
   loads instantly (§50);** the live path is the "one live patient" and is currently latency-variable.

**Honest conclusion:** the ≤ 90 s target is *achievable* (Session A proves it) but **not currently
guaranteed** under Gemini-3.7-flash load. The demo relies on the precomputed path for reliability; the live
path is shown as a real (variable-latency) capability, not a guaranteed-fast one.

## Model B corruption suite (§22)

Measured by `scripts/measure_model_b_live.py` (LIVE — real
`GeminiInteractionsClient`, `gemini-3.5-flash`) against the §22 Set D / Set M
corruption suite (`app.review.corruption`), built from demo Patient A's own
chart + claim plus a small control set of other demo patients' genuinely
correct, uncorrupted claims (B, D, E).

**LIVE RUN — 2026-08-20** (`scripts/measure_model_b_live.py`, Model B `gemini-3.5-flash`).

| Metric | Result | Release-gate requirement (§22.3) | Pass? |
|---|---|---|---|
| Set D blocked pre-Model-B | **7/7 (100%)** | 100% (7/7) | ✅ |
| Set M catch rate | **8/8 (100%)** | ≥ 80% | ✅ |
| Set M false-accept | **0** | (informational — corruptions not caught) | — |
| Control false-reject rate | **3/4 (75%)** | ≤ 20% | ❌ |
| **§22.3 release threshold met** | **False** | all three above must pass | ❌ |

**Decision: ADVISORY (badge WITHHELD).** `release_threshold_met` returned
`False`. Set D and Set M both passed handily (the deterministic layer blocked
100% of deterministically-catchable corruptions before Model B, and Model B
caught 100% of the model-only semantic corruptions with zero false-accepts),
**but the control false-reject rate was 75% (3 of 4 genuinely-correct claims
were wrongly rejected)**, far above the ≤20% ceiling.

**Interpretation (honest):** Model B, primed to *falsify* claims (§21.3), is
over-aggressive — excellent sensitivity to corruption, poor specificity on
correct claims. This is precisely the failure §22.3 exists to catch. Per the
spec, the product therefore does **not** display an "Independent review ✓
passed" badge; Model B's verdicts are shown as **ADVISORY** context only, and
the deterministic gates (§16–18) remain the authoritative safety layer.

**Not tuned to fit:** per §22.3, we did NOT re-tune Model B's prompt against
this same suite and re-report a flattering number. The measured 75%
false-reject stands as the honest result. A real fix (a less trigger-happy
reviewer prompt, or a two-of-three reviewer vote) would need to be measured
against a *separate, independently-authored* control set — which does not yet
exist (see §52 caveat below). Re-measure before ever claiming the badge.

## Regression vs evaluation (§52)

**The 5 hand-authored demo patients (A–E) are a SAFETY/REGRESSION suite, not
a statistically valid benchmark.** They exist to pin down specific,
deliberately-designed clinical scenarios (an unresolved high-severity
potassium finding, a resolved/normal case with no false alarm, an ambiguous
unit routed to human review, two general completion cases) and catch
regressions in the pipeline's handling of each — not to estimate any
real-world accuracy, sensitivity, specificity, or catch rate across the
actual distribution of patients, charts, or claims a production deployment
would see. There is **no independent holdout set**: every patient/cassette
here was hand-authored by the same people who built the pipeline being
tested against them, so a systematic blind spot in the corpus and in the
pipeline could coincide undetected.

The §22 Set M corruption suite (8 categories) is similarly **small and
hand-authored** (§22.2 caveat carried forward here): it demonstrates that
Model B *can* catch each of 8 specific, deliberately constructed semantic-
corruption patterns applied to one or a few base claims, not a statistically
grounded estimate of Model B's catch rate against the full space of ways a
claim can be subtly wrong. A high measured catch rate on this suite is
necessary evidence, not sufficient evidence, that Model B is safe to rely on
in production. Any release decision built on the §22.3 threshold should be
read with this scope explicitly in mind, and re-measured whenever the
corruption taxonomy, the base claims, or the underlying model changes.

## Accessibility (§57A)

Phase 13 ran the automated accessibility gate (`vitest` + `jest-axe`) against
the dashboard, the flagged-patient view, and the open evidence drawer:
**3/3 checks passed, zero serious/critical violations** (see
`evidence/phase_13.txt`), and `prefers-reduced-motion` is honored.

**Still pending (not yet performed): a manual keyboard-only navigation pass
and a manual greyscale/color-contrast visual pass.** Automated axe coverage
catches a meaningful subset of accessibility issues (missing labels, role/
name/value problems, contrast ratios it can compute) but does not verify
actual keyboard operability end to end or how the UI reads without color as
a channel — both require a human pass before this can be called complete
against §57A.
