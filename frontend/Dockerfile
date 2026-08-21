# ChartPilot frontend container (Next.js 15 standalone, spec §76A.1 sibling).
#
# BUILD CONTEXT IS `frontend/` (conventional: `docker build frontend/`, or
# `docker build -f frontend/Dockerfile frontend/`) so `frontend/.dockerignore`
# is auto-discovered from the context root.
#
# This app renders entirely from baked-in mock data (`lib/mockData.ts`) --
# no backend calls, no env vars, no secrets. It is a self-contained public
# demo UI, so the image needs nothing injected at build or run time beyond
# Cloud Run's `PORT`.
#
# Multi-stage: `deps` installs the pinned dependency set with `pnpm` from
# `pnpm-lock.yaml` (no devDependencies pruning needed here since the build
# stage needs them for `next build`, e.g. `typescript`/`@types/*`); `builder`
# copies deps + full source and runs `next build`, which -- because
# `next.config.ts` sets `output: "standalone"` -- writes a self-contained
# server to `.next/standalone` (minimal traced `node_modules` + `server.js`)
# and static assets to `.next/static`; `runner` copies only those artifacts,
# runs as a non-root user, and binds `$PORT` (Cloud Run's contract) rather
# than a hard-coded port.
#
# Base image pinned to an explicit tag AND content digest (no floating
# `latest`) -- resolved via:
#   docker pull node:22-slim
#   docker inspect --format='{{index .RepoDigests 0}}' node:22-slim
# on 2026-08-21. Bump both the tag and the digest together on a deliberate
# upgrade; never let this float.
ARG NODE_IMAGE=node:22-slim@sha256:d649c27dae7ba0137b3cef5dd75baa422c08dc3d9e3fc0c23dfb172dc3cc6436

FROM ${NODE_IMAGE} AS deps

WORKDIR /app

# Pinned to the exact pnpm version this repo's lockfile was produced with
# (see `packageManager` in package.json), so the resolver behaves
# identically in CI/prod as it does locally.
RUN corepack enable && corepack prepare pnpm@10.30.3 --activate

# Copy only the dependency manifests first so this (expensive) layer stays
# cached across app-code-only changes.
COPY package.json pnpm-lock.yaml ./

# --frozen-lockfile: fail the build rather than silently re-resolving if
# pnpm-lock.yaml is stale relative to package.json.
RUN pnpm install --frozen-lockfile

FROM ${NODE_IMAGE} AS builder

WORKDIR /app

RUN corepack enable && corepack prepare pnpm@10.30.3 --activate

COPY --from=deps /app/node_modules ./node_modules
COPY . .

# No env vars / secrets needed -- the app renders from baked-in mock data.
RUN pnpm build

# This app currently ships no public/ dir. Guarantee it exists so the
# unconditional COPY in the runner stage below never fails, without making
# that COPY depend on repo state.
RUN mkdir -p /app/public

FROM ${NODE_IMAGE} AS runner

# Non-root runtime user (uid/gid 1000). `node:22-slim` already ships a
# `node` user/group at exactly 1000:1000 -- reuse it rather than creating a
# second one, which collides on the GID and fails the build.
WORKDIR /app

ENV NODE_ENV=production \
    HOSTNAME=0.0.0.0

# Standalone output already contains a minimal, traced node_modules plus
# server.js -- nothing else from node_modules needs to be copied.
COPY --from=builder --chown=node:node /app/.next/standalone ./
COPY --from=builder --chown=node:node /app/.next/static ./.next/static

# public/ is optional in this app; copy it only if present.
COPY --from=builder --chown=node:node /app/public ./public

USER node

# Default only -- Cloud Run injects the real `PORT` at runtime and it must
# never be hard-coded. The Next.js standalone `server.js` reads `PORT` (and
# `HOSTNAME`) directly from the environment.
ENV PORT=8080
EXPOSE 8080

CMD ["node", "server.js"]
