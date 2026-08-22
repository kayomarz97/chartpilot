# CLAUDE.md — Working Agreement for ChartPilot (doctor_helper)

> The rules Claude Code follows **every session** in this repo. Kept short on purpose: a long
> file gets half-ignored. This complements the global `~/.claude/CLAUDE.md` (plan-first,
> long-term fixes, secrets, git discipline, agents, ledgers) — it does NOT repeat it.
> Only the project-specific sections below matter; everything else is inherited.

---

## ⭐ STANDING ORDER (default every session — never needs restating)

**Sonnet builds, Opus orchestrates + verifies.** For ALL implementation work in this repo:
delegate the coding to **Sonnet subagents** (`Agent` tool, `model: sonnet`); the **Opus** main
session writes the brief, then INDEPENDENTLY runs `make check` and reads the load-bearing files,
and is the ONLY one that commits/tags. Builders never commit. This is automatic — do NOT ask the
user to confirm it each time (TD-009, LOCKED). **Also keep `ARCHITECTURE.md` true in the same
change** whenever structure/names/enums/commands change.

---

## Project at a glance (the WHAT)

ChartPilot is a **pre-clinic chart-prep agent** (hackathon prototype, synthetic FHIR data only —
not a medical device, not clinically validated). It reads a patient's FHIR record and produces a
one-page safety brief where **deterministic code owns every fact, the LLM is only an editor, an
evidence+citation layer forbids unsupported claims, a blinded second model tries to falsify each
claim, and a final gate fails closed.** Stack: **Python 3.11 + FastAPI backend** (`backend/`, `uv`),
**Next.js/TypeScript frontend** (`frontend/`, `pnpm`), deployed on **Google Cloud Run** (Scheduler →
Cloud Tasks → private Cloud Run → Gemini → Firestore → public read-only UI) in the isolated GCP
project `chartpilot-agentic` (`asia-south1`).

**Codebase map:** read **`ARCHITECTURE.md` FIRST** (project root) — it names every module, the key
class/function/variable names, the enum/status values, and the exact commands, so you navigate by the
map instead of burning tokens on exploratory greps. `README.md` is the narrative; `SPEC.md` is the
authoritative control document.

**Directories that matter** (point, don't describe):
- `backend/app/` — the pipeline code that gets edited (per-stage subpackages: `fhir/ normalize/
  rules/ validation/ evidence/ agent/ citation/ review/ gate/ pipeline/ storage/ tasks/ api/`).
- `backend/tests/` — mirrors `app/`; network-blocked; how correctness is proven.
- `frontend/` — Next.js dashboard, evidence drawer, manual-review panel.
- `infra/` — ordered, idempotent GCP deploy scripts (hard-pinned to `--project=chartpilot-agentic`).
- `ARCHITECTURE.md` — **read BEFORE searching the codebase.**

## Commands (exact — don't guess)

```bash
cd backend && uv sync                 # install backend deps
make check                            # THE verify gate: ruff + mypy(strict) + pytest(network-blocked)
                                      #   + secret-scan + no-sampling-params gate. Must exit 0 before "done".
cd frontend && pnpm install && pnpm run build && pnpm test   # frontend build + axe a11y
make live-test                        # ⚠️ COSTS REAL GEMINI TOKENS — needs GEMINI_API_KEY in backend/.env (gitignored)
```

⚠️ `make live-test` and anything in `infra/` hit real cloud / cost money — never run without intent.
The offline path (`make check`) needs no network and no key; prefer it for verification.

**Branches:** work on and push `dev` (or a feature branch); **never push `main`** — the user merges it.
Never commit secrets; run `secret-scanner` before every push.

---

## Project-specific rules (these OVERRIDE nothing global; they ADD to it)

1. **`ARCHITECTURE.md` is a first-class artifact — keep it TRUE in the SAME piece of work.**
   Whenever you add, move, rename, repurpose a module, or change a load-bearing class/function/enum
   name, status value, env var, or command, **update `ARCHITECTURE.md` in the same change** (and in
   the same commit). A stale map is worse than none. Never finish a task that altered structure
   without updating it. Read it before searching; edit it before committing.

2. **Two-tier operating model (TD-009, LOCKED user directive): Sonnet builds, Opus orchestrates.**
   - **Opus (main session) = orchestrator/architect/verifier.** Writes the plan/brief for each phase,
     routes work, INDEPENDENTLY re-runs `make check`, reads the load-bearing files, and is the ONLY
     one that commits + tags. Keep Opus's own token use lean — delegate implementation, don't hand-code.
   - **Sonnet subagents = builders.** Spawn implementation work via the Agent tool with `model: sonnet`.
     Builders implement against the brief and report back; **builders must NOT commit, tag, or push.**
   - When in doubt, Opus plans and verifies; Sonnet writes the code.

3. **Safety invariants are not negotiable in any refactor** (`SPEC §53`): deterministic layer owns
   facts, free text is `trusted=False`, the final gate fails closed, failures surface as
   `FAILED`/`FLAGGED_FOR_REVIEW` — never a silent "no findings." The byte-equal prompt-injection
   invariant test must stay green.

---

## Everything else is global

- Golden loop (plan → read `ARCHITECTURE.md`/docs → check ledgers → build → verify → log stumbles),
  the non-negotiable rules, and the agent routing table live in `~/.claude/CLAUDE.md`.
- Per-phase build protocol (machine-checkable gates, `evidence/phase_NN.txt`, `journal.md`,
  `git tag phase-NN`) is described in `SPEC §64/§65` and `README.md`.
- Non-obvious decisions live in `TECHNICAL_DECISIONS.md` (TD-001…); stumbles → `journal.md` mistakes
  ledger via `mistake-tracker`.
