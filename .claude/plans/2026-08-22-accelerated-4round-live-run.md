# Plan — Accelerated 4-round self-improving live run

**Date:** 2026-08-22 · **Mode:** accelerated (4 rounds back-to-back, not 4 calendar days)
**Labels:** the user (physician) labels each round in the terminal, Q&A style.
**Status:** in progress

> Goal (plain): simulate 4 "mornings." Each round, 8 NEW synthetic patients are run through the
> REAL pipeline; the doctor reviews them in the terminal and marks Confirm/Override/Correct; the
> self-improving loop learns from those labels + the deterministic citation signal, proposes a
> better Model-A prompt, and promotes it only if it beats a held-out benchmark. Round N+1 uses the
> improved prompt. After 4 rounds, update the README's measured numbers with the REAL before/after —
> better or not; never fabricated.

## Honesty contract (non-negotiable)
- The README numbers change to the REAL measured post-run results. If the loop improves the
  citation verified-span rate / clinician agreement, the better numbers go in. If it improves less
  than hoped (or not at all), the true numbers go in, with the honest caveat. Measured honesty is
  the whole differentiator (README already withholds a badge over a 75% false-reject).
- Every live number is from a real Gemini call. Nothing is precomputed or faked.

## Prerequisites
- [x] Spend cap raised (journal updated).
- [ ] Live path confirmed with 1 patient (de-risk run in progress; latency measured).
- [ ] Firestore ledger migration merged (for the deployed path; the accelerated LOCAL run uses the
      file-backed ledger, which is fine here).
- [ ] Ambient key hazard handled: every live invocation uses `env -u GEMINI_API_KEY -u GOOGLE_API_KEY`
      so Settings falls back to our chartpilot key in `backend/.env` (NOT the ambient Iatronix key).

## Build (Sonnet, after the ledger API settles)
1. `scripts/gen_patients.py` — generate varied synthetic FHIR bundles (vary potassium 3.5–7.0,
   ACE/ARB/K-sparing meds present/absent, creatinine/eGFR, ages/sex) so findings + citation loads
   vary across the 32 patients. Deterministic seedless (index-derived) so a round is reproducible.
2. `scripts/live_round.py` — for a round: resolve the ACTIVE Model-A prompt from the ledger, run
   each of the round's 8 patients through `run_patient` live (real Gemini A+B), write each patient's
   findings + citation verdicts + verified-span rate to a round JSON. COSTS TOKENS; never in `make check`.
3. `scripts/improve_round.py` — given the round's presentations + the doctor's labels, run
   `run_improvement_cycle` (real LlmProposer + live evaluator) and record: proposed?/accepted?/
   promoted?, plus metrics_before/after. Updates the ledger on accept.
4. A small metrics tracker so the 4-round trajectory (verified-span rate + clinician agreement per
   round) can be tabulated for the README.

## Execute (interactive, main session drives)
For round in 1..4:
  a. Run `live_round.py` for the round's 8 patients (poll to completion; report progress).
  b. Present each patient's findings to the doctor in the terminal (statement, verdict, citation,
     Model-B note) and collect Confirm / Override / Correct via AskUserQuestion, persisted as
     ClinicianActions.
  c. Run `improve_round.py` → propose/evaluate/(promote). Report what happened + metrics.
  d. Carry the (possibly promoted) prompt into round N+1.

## Finalize
- Tabulate the 4-round before/after. Update `README.md`'s "Measured results" section with the REAL
  numbers (replacing/annotating the current 75% false-reject + rates as appropriate), and
  `EVALUATION.md` with the full trajectory. Add a journal entry + TD note if a prompt was promoted.
- Commit each round's artifacts + the final README/EVALUATION update on `dev`.

## Risks / honest limits
- **Latency:** Model A ~1–3 min/patient ⇒ a round of 8 is ~10–25 min of wall-clock; 4 rounds is
  significant. I poll to completion and never kill a paid run.
- **Narrow signal:** the pipeline has one clinical rule (K_HIGH_RISK_001) + validity metrics, so the
  main improvement axis is the citation verified-span rate. The "self-improvement" is real but narrow;
  I'll say so.
- **Improvement not guaranteed:** the loop may legitimately not beat the baseline in 4 short rounds.
  That's a valid, honestly-reported outcome — not a failure to paper over.
