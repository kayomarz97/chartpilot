# `tests/live/`: the live-integration layer (spec §23)

Everything else under `backend/tests/` is hermetic: no real network calls,
Gemini responses come from `FakeGeminiClient` cassettes
(`tests/fixtures/demo/cassettes/*.json`), and `make check` enforces this with
`pytest-socket` (`--disable-socket` in `pyproject.toml`'s `[tool.pytest.ini_options]`).

This directory is the one deliberate exception: it runs the REAL pipeline
(`app.pipeline.runner.run_patient`) against the REAL Gemini API, for real
patient-shaped demo data, over the network.

## Why it's excluded from `make check`

- **Costs real tokens / real money.** Every run makes real Model A + Model B
  API calls.
- **Not deterministic.** Model output varies run to run, so these tests only
  assert robust, structural properties (the run completes with no error,
  reaches the terminal `PERSISTED` stage, and produces at least one
  finding), never exact model wording or an exact finding count.
- **Needs a real `GEMINI_API_KEY`.** In CI, and on any machine without a key
  set, the test module skips itself cleanly (`allow_module_level=True`);
  it never fails for lack of a key.

Two independent guards keep it out of the default suite:
1. Every test is `@pytest.mark.live`, and `pyproject.toml`'s `addopts`
   includes `-m "not live"`.
2. `addopts` also includes `--disable-socket` (blocking all real network
   sockets by default); each live test additionally carries
   `@pytest.mark.enable_socket` (a `pytest-socket` marker) so it can reach
   the network when deliberately selected.

## How to run it on purpose

```bash
cd backend
GEMINI_API_KEY=<your real key> uv run pytest tests/live -m live
```

(If `GEMINI_API_KEY` is already exported in your shell, e.g. from
`backend/.env` via your own shell profile, you can drop the inline
assignment.) The `-m live` on the command line overrides the `-m "not live"`
baked into `addopts`, and each test's own `enable_socket` marker re-permits
sockets for that test only; the rest of the suite stays blocked. This exact
command was verified to (a) collect and run the test when a key is present
and (b) skip cleanly with no failure when it is not.

Verified working, without spending real tokens, via:

```bash
# No key set -> collects 0, skips 1, exits 0 (never fails for lack of a key).
env -u GEMINI_API_KEY uv run pytest tests/live -m live -v

# Key present -> collects the real test cleanly (no import/collection errors).
uv run pytest tests/live -m live --collect-only
```

## What it needs

- `GEMINI_API_KEY` set in the environment (a real, working Gemini API key).
- Network access to the real Gemini API.
- Willingness to spend real tokens on one live pipeline run.

## What it does NOT do

- It is never part of `make check` or any CI gate.
- It never asserts exact model prose (see
  `tests/unit/test_no_prose_assertions.py`, which enforces this suite-wide).
