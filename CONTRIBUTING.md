# Contributing to ChartPilot

> ChartPilot is a hackathon prototype on **synthetic data only** — not a medical device, not
> clinically validated. Please keep that framing in any change: the safety story is the point.

## The one gate that matters

Every change must keep the offline verification gate green:

```bash
cd backend && uv sync        # one-time: install backend deps (Python 3.11 + uv)
cd .. && make check          # ruff format + ruff check + mypy + pytest (network-blocked)
                             #   + secret scan + no-sampling-params gate. Must exit 0.
```

`make check` is **hermetic**: it needs no network, no cloud, and no Gemini key, so it runs the
same on your laptop and in CI (`.github/workflows/ci.yml`). The frontend has its own build + a11y
check:

```bash
cd frontend && pnpm install && pnpm run build && pnpm test
```

Anything that touches the live cloud or costs Gemini tokens (`make live-test`, `infra/`) is
**manual and opt-in** — never part of `make check`.

## Ground rules

1. **Branches.** Work on `dev` or a feature branch; open PRs into `dev`. `main` is the released line.
2. **Safety invariants are non-negotiable.** Deterministic code owns every fact; free text is
   `trusted=False`; the final gate **fails closed**; failures surface as `FAILED` /
   `FLAGGED_FOR_REVIEW`, never a silent "no findings." Do not weaken these in a refactor.
3. **Never commit secrets.** Copy `backend/.env.example` to `backend/.env` (gitignored) for local
   keys. The secret scanner runs inside `make check` and in CI.
4. **Keep the docs true.** If you change a module, enum, status value, command, or env var, update
   `ARCHITECTURE.md` in the same change.

See `ARCHITECTURE.md` for the codebase map and `TECHNICAL_DECISIONS.md` for the "why" behind the
non-obvious choices.
