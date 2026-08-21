# ChartPilot backend container (spec §76A.1).
#
# BUILD CONTEXT IS `backend/` (conventional: `docker build backend/`, or
# `docker build -f backend/Dockerfile backend/`) so `backend/.dockerignore`
# is auto-discovered from the context root.
#
# KNOWN GAP (flagged, not silently worked around): `app/agent/model_pin.py`
# reads the repo-root `config/models.yaml` at runtime (resolved via
# `Path(__file__).resolve().parents[3]`), which lives OUTSIDE `backend/` and
# therefore OUTSIDE this build context -- it is NOT copied into this image.
# This is safe for Part A: nothing wired up in `app/api/routes.py` this
# phase (§76A.1) calls `load_model_pin`/`verify_pinned_models` -- the real
# per-patient handler is a deliberate `NotImplementedError` stub pending
# Phase 19's live Gemini wiring. Before Phase 19 wires a real handler that
# DOES call `load_model_pin`, either (a) switch this build to a repo-root
# context and add `COPY ../config /app/config` (plus move/duplicate
# `.dockerignore` to `backend/Dockerfile.dockerignore` so BuildKit still
# finds it), or (b) move `config/models.yaml` under `backend/config/`. Do
# not let a Phase 19 handler silently ship without one of these.
#
# Multi-stage: `builder` resolves + installs the pinned dependency set with
# `uv` from `uv.lock` (no compiler/toolchain ships in the runtime image);
# `runtime` copies only the resulting virtualenv + application code, runs
# as a non-root user, and binds `$PORT` (Cloud Run's contract) rather than a
# hard-coded port.
#
# Base image pinned to an explicit tag AND content digest (no floating
# `latest`) -- resolved via:
#   docker pull python:3.11-slim
#   docker inspect --format='{{index .RepoDigests 0}}' python:3.11-slim
# on 2026-08-21. Bump both the tag and the digest together on a deliberate
# upgrade; never let this float.
ARG PYTHON_IMAGE=python:3.11-slim@sha256:9c900dea9e8fb7e16277c179b555cc72d29a352dbc33cff48ad5a0412fd5bfc7

FROM ${PYTHON_IMAGE} AS builder

# Pinned to the exact `uv` version this repo's `.venv`/lockfile was produced
# with, so the resolver behaves identically in CI/prod as it does locally.
RUN pip install --no-cache-dir uv==0.10.7

WORKDIR /app

# Copy only the dependency manifests first so this (expensive) layer stays
# cached across app-code-only changes.
COPY pyproject.toml uv.lock ./

# --frozen: fail the build rather than silently re-resolving if uv.lock is
# stale relative to pyproject.toml. --no-dev: the runtime image never needs
# mypy/pytest/ruff. This project's pyproject.toml has no [build-system]
# table (it isn't an installable package, just an app + a lockfile), so
# `uv sync` here only materializes the dependency virtualenv -- no project
# build/install step happens or is needed.
RUN uv sync --frozen --no-dev

FROM ${PYTHON_IMAGE} AS runtime

# Non-root runtime user (spec §76A.1) -- no login shell, no home directory.
RUN groupadd --system --gid 1000 chartpilot \
    && useradd --system --uid 1000 --gid chartpilot --no-create-home \
       --shell /usr/sbin/nologin chartpilot

WORKDIR /app

COPY --from=builder --chown=chartpilot:chartpilot /app/.venv ./.venv
COPY --chown=chartpilot:chartpilot app ./app

ENV PATH="/app/.venv/bin:${PATH}" \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1

USER chartpilot

EXPOSE 8000

# Shell form (not exec-array) so `${PORT:-8000}` actually expands -- Cloud
# Run injects `PORT` at runtime and it must never be hard-coded (spec
# §76A.1). `exec` replaces the shell with the uvicorn process so it becomes
# PID 1 and receives SIGTERM directly for graceful shutdown.
CMD exec uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8000}
