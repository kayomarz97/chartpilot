# Phase 21 — Enrich demo, wire UI to live backend, PubMed guidelines, README overhaul

Date: 2026-08-21 · Branch: `dev` (→ merge to `main` at end, per explicit user override of the
"user merges main" rule). Prev checkpoint: `phase-19` + live deploy fixes (commit b4cdd85).

## User decisions (AskUserQuestion, 2026-08-21) → TECHNICAL_DECISIONS TD-010..TD-013
- **TD-010 Error patients:** keep ONE failure patient, clearly labeled as an intentional "Safety
  demonstration"; convert the other error patient to a rich success case.
- **TD-011 Backend visibility:** wire the UI to show REAL live backend data — add a PUBLIC read-only
  endpoint on the backend that serves persisted run results from Firestore; the Next.js dashboard fetches
  and renders it (falls back to the enriched authored demo data if the backend is unreachable, so the site
  is never broken).
- **TD-012 Guidelines:** add PubMed guideline-PUBLICATION-TYPE citations (E-utilities `ptyp=Guideline`).
  These are GUIDELINE-tier but `reviewed_by=PENDING`, so the existing gate caps them at PARTIALLY_VERIFIED.
  Correct the misconception that PubMed provides licensed guideline TEXT — it provides citations/abstracts;
  the actual guideline text stays behind its publisher's license. No copied guideline text.
- **TD-013 Push to main:** merge dev→main and push at the end (explicit override of standing rule).

## Architecture decisions (Opus)
### Live-data contract (backend → frontend)
New PUBLIC endpoint: `GET /runs/{run_id}` (CORS enabled) →
```
{ "run_id", "generated_at", "patients": [ {
    patientId, patientName, status, stage,
    findings: [ { claimId, claimType, statement, severity, verdict, rationale,
                  recommendedAction, patientEvidence[], externalEvidence[] } ],
    timeline: [ { date, kind, label, detail, severity? } ],
    labs:     [ { analyte, unit, points: [ { date, value } ] } ]   // for trend sparklines
} ] }
```
This is the frontend `PatientRun` shape + a `labs` array for trends.
- **Persistence:** at finalize, the worker also writes a `presentation` doc
  (`runs/{run_id}/patients/{pid}` gets a `presentation` field, or a sibling doc) holding exactly this
  UI-shaped payload. Keeps the read endpoint a trivial Firestore read (no re-derivation).
- **Where the payload is built:** `run_patient` returns the normalized observations + timeline it already
  computes (additive field on `PatientRunResult`, low-risk); the composition maps `PatientRunResult` → the
  UI payload and persists it. Read endpoint returns it verbatim.
- **Public + safe:** read-only, synthetic data only, no secrets. The write path stays private/OIDC.

## Workstreams (Sonnet builds; Opus writes briefs, verifies `make check`, deploys, commits, tags)
### 21a — Backend: presentation payload + public read endpoint + CORS
- `PatientRunResult` gains an additive `normalized_labs`/timeline surface; composition builds the UI payload;
  worker persists it; `GET /runs/{run_id}` (public, CORS) reads + returns it. Hermetic tests.
### 21b — Evidence: PubMed guideline citations (TD-012)
- Extend the PubMed adapter to query `ptyp=Guideline`; surface GUIDELINE-tier, `reviewed_by=PENDING`
  records; never present as licensed text; the gate already caps them at PARTIALLY_VERIFIED. Hermetic
  cassette tests. (Parallel with 21a — different files.)
### 21c — Enrich demo FHIR bundles (long, realistic histories)
- Rewrite `backend/app/demo_data/patient_*.json` (+ keep `tests/fixtures/demo` in sync) with LONG
  longitudinal histories (years of labs/meds/diagnoses/encounters) so live runs produce rich timelines +
  lab trends. Keep them SYNTHETIC (no PHI). Re-record cassettes if needed so `make check` stays hermetic.
### 21d — Frontend: enrich + relabel + collapsible history/labs/trends panel + wire to live data
- Enriched authored `mockData.ts` (long histories) as the fallback; convert one error patient to a rich
  success; keep one failure under a clearly-labeled "Safety demonstration" section (TD-010).
- New COLLAPSIBLE panel per patient: patient history + recent labs WITH TRENDS (inline SVG sparklines, no
  new dependency) for manual review, sitting alongside the AI findings — cohesive layout.
- Fetch live data from `GET {BACKEND}/runs/{run_id}` (public); render real statuses/findings; graceful
  fallback to authored data if unreachable. Backend URL via `NEXT_PUBLIC_BACKEND_URL` build arg.
### 21e — README overhaul (technical + non-technical, per the two-register house rule)
- Detailed **flowchart(s)**: the mermaid component diagram + a sequence diagram of one run + the deploy
  topology. Plain-language walkthrough AND technical detail for every stage.
- **"Why this wins" highlights** section.
- **"Built cleanly with AI agents, to make better AI agents — and the work is visible"**: explain the
  20-phase protocol, `journal.md`, `evidence/phase_*.txt`, git phase tags, Sonnet-builds/Opus-verifies,
  the two live-found bugs — the process itself is a differentiator and is auditable in the repo.
- Correct the PubMed-vs-guidelines point honestly.
### 21f — Integrate, deploy, document, ship
- Redeploy backend (read endpoint + guidelines) and frontend (new UI + live wiring); re-run a live smoke to
  populate Firestore; verify the UI shows real data. Update `journal.md` + `TECHNICAL_DECISIONS.md`
  (TD-010..013); record `evidence/`; tag `phase-21`. Push `dev`; then merge `dev`→`main` and push `main`.

## Guardrails carried forward
Isolated project `chartpilot-agentic` only (TD-002); every gcloud pinned + guarded; no secrets; `make check`
green at each step; Sonnet builds / Opus verifies + deploys; nothing claimed working without a real run.
