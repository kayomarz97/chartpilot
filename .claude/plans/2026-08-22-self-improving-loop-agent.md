# Plan — Self-Improving Loop Agent for ChartPilot

**Date:** 2026-08-22 · **Author:** Opus (orchestrator) · **Status:** DRAFT for user approval
**Slug:** self-improving-loop-agent

> Plain-language goal: today ChartPilot runs the same pipeline every night and never gets
> better on its own. This plan adds two feedback loops — a *within-run* retry loop so the
> agent fixes its own failed citations instead of giving up, and an *across-runs* learning
> loop that watches clinician overrides + gate failures and proposes measured improvements,
> **without ever being allowed to rewrite clinical facts, rules, or the safety gate on its own.**
>
> Technical goal: close two feedback edges on the existing `run_patient` pipeline while
> preserving the SPEC §53 invariant (deterministic layer owns facts; free text is
> `trusted=False`). Every self-change is gated by the existing offline eval harness.

---

## 0. Guardrails this plan must NOT violate (read first)

- **The tiering rule** — what may change itself:
  | Tier | Examples | Approval path |
  |---|---|---|
  | **AUTO** | Model-A prompt wording, evidence-retrieval ranking, inner retry strategy | passes offline eval → auto-promote |
  | **HUMAN-GATED** | Model-B threshold, gate strictness, latency/token budgets | agent *proposes* a diff → human approves |
  | **FROZEN** | clinical rules (`K_HIGH_RISK_001`, eGFR), the final fail-closed gate, normalization | agent may *draft*, human authors + tests + signs off |
- **Fail-closed is preserved.** A retry that exhausts its budget yields `FAILED`/`FLAGGED_FOR_REVIEW`,
  never a silent "no findings," never a downgraded gate.
- **No self-tuning against the held-out eval.** The outer loop optimizes against clinician-labeled
  cases + a *frozen* benchmark it cannot train on (avoids the Model-B "game the number" trap the
  README already calls out at 75% false-reject).
- **SPEC §53 byte-equal invariant test must still pass** after every change.

---

## Phase A — Inner loop: gate-failure → revise → retry (within one run)

**What it does (plain):** when a citation gate rejects Model A's quote, feed the *reason* back to
Model A and let it try again with a real evidence region, up to a small budget, before failing.

**Where it hooks in (real files):**
- `app/pipeline/runner.py` — the stage sequencer. Add a bounded revise-loop around the
  Model-A → citation-gate segment (do **not** loop the final gate or Model B).
- `app/citation/verifier.py` — already returns per-gate pass/fail; extend its result to carry a
  structured `revision_hint` (which gate failed, the computed evidence region/offsets) — this is
  *deterministic* data, stays `trusted=False` toward facts.
- `app/agent/prompts.py` + `app/agent/gemini.py` — add a "revise" prompt variant that takes the
  prior claim + the deterministic hint and re-emits a claim with a corrected verbatim span.
- `app/pipeline/models.py` — add `max_revise_iterations` (default 2) + per-attempt trace fields.

**Budget & failure:** reuse the existing timeout → `TIMED_OUT` path; cap iterations; every attempt
is recorded (for the outer loop). Exhausted budget → existing `FAILED`/review path unchanged.

**Verification:** unit test that a deliberately-wrong span gets corrected within budget; test that
budget exhaustion still fails closed; SPEC §53 invariant test still green.

---

## Phase B — Signal collection (the data the outer loop learns from)

**What it does (plain):** record, for every run, what the gates rejected, where Model B disagreed,
and — most valuable — what the *clinician* did in the review panel (accept / override / correct).

**Where it hooks in:**
- `app/storage/models.py` + `app/storage/repository.py` — add a `RunSignal` / `ClinicianAction`
  record type (append-only) alongside the existing two-phase claim/evidence commit.
- `app/storage/two_phase.py` — persist per-attempt gate outcomes + Model-B verdicts as signals
  (already computed; we're just retaining them).
- `app/api/routes.py` + `app/api/presentation.py` — add an endpoint for the frontend review panel
  to POST a clinician action (`OVERRIDE` / `CONFIRM` / `CORRECT` + free-text note, stored
  `trusted=False`).
- Frontend review panel — add the accept/override control (small change; wire to new endpoint).

**These clinician actions are the ground-truth labels** the outer loop optimizes toward.

---

## Phase C — Outer loop: propose → prove → canary → promote (across runs)

**What it does (plain):** a separate scheduled job that reads the accumulated signals, proposes an
improvement to an AUTO-tier component, and only ships it if it beats the current version on a frozen
benchmark — otherwise it's discarded or handed to a human.

**Where it hooks in (mostly new, isolated module `app/improve/`):**
- `app/validation/metrics.py` + `app/validation/engine.py` — the existing eval/fitness harness;
  the outer loop scores candidates here (extend, don't replace).
- `app/review/corruption.py` — the corruption suite = part of the frozen regression benchmark.
- **New `app/improve/collector.py`** — aggregates `RunSignal`/`ClinicianAction` into a dataset +
  a "failure museum."
- **New `app/improve/proposer.py`** — an agent that proposes a candidate diff for exactly ONE
  AUTO-tier target (e.g. a revised Model-A prompt or retrieval-ranking tweak). Emits a diff, never
  writes to `app/rules/` or `app/gate/`.
- **New `app/improve/evaluator.py`** — replays candidate vs current against the frozen benchmark +
  clinician-labeled cases; accept only on strict improvement + zero regression.
- **New `app/improve/promote.py`** — versions the artifact (prompt/config), keeps the prior as the
  rollback unit (mirrors the `phase-NN` tag pattern), and canaries on a slice before full promote.
- **New scheduled trigger** — a second Cloud Scheduler job (weekly) → `POST /improve-run`, reusing
  the existing OIDC-invoker pattern from `app/tasks/enqueue.py`.

**Hard stop in code:** `proposer.py` must refuse (raise) if a candidate touches a FROZEN-tier path.
Add a test asserting that.

---

## Phase D — Docs, safety write-up, evidence

- Update `ARCHITECTURE.md` (new `app/improve/` module + the two loops) — **same piece of work**.
- Add TD-014 to `TECHNICAL_DECISIONS.md`: the tiering rule + "no training on held-out eval."
- Extend `EVALUATION.md`: before/after metric of the inner-loop citation-repair rate.
- `SPEC` note: the self-improving loop is AUTO-tier only; clinical truth stays FROZEN + clinician-owned.

---

## Sequencing & who does what

Per **TD-009**: Opus (this session) orchestrates + writes each phase brief + independently verifies
(`make check`) + commits/tags. **Sonnet subagents implement** each phase; they never commit.

1. **Phase A** (inner loop) — smallest, highest-value, self-contained. Do first.
2. **Phase B** (signals) — needed before C can learn.
3. **Phase C** (outer loop) — largest; isolated in `app/improve/` so it can't destabilize the pipeline.
4. **Phase D** (docs/eval) — folded into each phase, finalized at the end.

Each phase ends only when `make check` exits 0, evidence is teed to `evidence/`, a `journal.md`
entry exists, and a checkpoint is tagged — the existing 20-phase protocol, continued.

## Open questions for the user (before building)
1. Scope now: build **Phase A only** first (inner retry loop — quick, visible win), or the full A→C?
2. For Phase B, is adding a clinician accept/override control to the frontend review panel in scope,
   or should we simulate clinician labels from the synthetic fixtures for now?
3. Weekly cadence for the outer loop OK, or different?
