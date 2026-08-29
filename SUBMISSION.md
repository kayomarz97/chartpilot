# ChartPilot: Devpost Submission (copy-paste ready)

> The live-demo URL and the demo-video URL are both filled in below. Everything here is ready to paste
> into Devpost.

---

## Project name
**ChartPilot**

## Elevator pitch (one line)
An agentic pre-clinic chart-prep assistant that turns longitudinal FHIR data into a clinician-facing
safety brief: where every finding carries verifiable evidence and a second AI model tries to disprove
it before you ever see it.

## Built with (Devpost "Built With" tags)
`python` `fastapi` `google-gemini` `google-genai` `nextjs` `react` `typescript` `google-cloud-run`
`cloud-tasks` `cloud-scheduler` `firestore` `secret-manager` `docker` `fhir` `openfda` `pubmed`

---

## Inspiration
Before a clinic visit, a doctor skims a chart in a couple of minutes and can miss something that matters:
a critical potassium in a patient on an ACE inhibitor, a lab that never got followed up. Most "AI + health"
demos pipe the chart straight into an LLM and trust whatever it says. That is exactly what you must **not**
do in medicine. ChartPilot was built to prove a safer pattern: **facts come from deterministic code and
cited evidence; the LLM is only an editor; a second model is an adversary; and a final gate refuses to pass
anything unproven.**

## What it does
ChartPilot autonomously prepares a **pre-visit safety brief** from FHIR R4 data:
1. **Reads & normalizes** the chart deterministically (units, observation status/supersession, timezone-
   and precision-aware timestamps, eGFR (CKD-EPI 2021), anion gap, corrected calcium).
2. **Runs deterministic clinical rules** (e.g. a high-risk-potassium rule): these own the facts, not the LLM.
3. **Retrieves current evidence** (openFDA drug labels, PubMed literature, a small human-review-pending
   guideline pack) into an **immutable, content-hashed snapshot**.
4. **Model A (Gemini 3.7-flash)** writes structured claims, each with a **verbatim evidence span**.
5. **Deterministic citation gates** verify every claim: source exists → content hash matches → span is
   really in the source → claim type/tier is consistent. Offsets are computed by us, never trusted from the model.
6. **Model B (Gemini 3.5-flash)** is **blinded** (never sees Model A's rationale/confidence) and tries to
   **falsify** each claim.
7. **A final safety gate fails closed:** a claim that fails any deterministic gate can never be VERIFIED;
   A/B disagreement is routed to human review; pending-review guidance is capped at PARTIALLY_VERIFIED.
8. **Durable, idempotent orchestration** (Cloud Tasks + checkpoints + dead-lettering) persists results to
   Firestore; a failure surfaces as FAILED/FLAGGED_FOR_REVIEW, **never** as a silent "no findings."

**The clinician remains the decision-maker.** ChartPilot surfaces and shows its work; it does not decide.

## How we built it
- **Backend:** Python 3.11 + FastAPI, `google-genai` (Gemini Interactions API). Deterministic-first
  architecture with a `ClinicalValidityEngine`, a citation verifier, a blinded Model-B harness + a
  corruption test suite, two-phase Firestore commit, and durable Cloud Tasks orchestration.
- **Frontend:** Next.js 15 / React 19 / TypeScript, dark Material-3 UI with an evidence drawer + timeline.
- **Cloud (all `asia-south1`, isolated project `chartpilot-agentic`):** Cloud Run (private, OIDC-authenticated),
  Cloud Tasks (per-patient, idempotent), Cloud Scheduler (nightly), Firestore (Native), Secret Manager
  (Gemini key). Two least-privilege service accounts (a runtime identity that touches Firestore vs. an
  invoker identity that may only *call* the service).
- **Engineering rigor:** a 20-phase build protocol with machine-checkable gates: every phase ends with a
  green `make check` (ruff + mypy strict + a network-blocked pytest suite + a secret scanner + a
  no-sampling-params gate) recorded to `evidence/phase_NN.txt` and an annotated git tag. 452 tests.

## Challenges we ran into
- **Making "independent review" real, not theater.** Model B is prompted to *falsify* and is blinded to
  Model A. We measured it honestly against a corruption suite, and it was **over-aggressive** (75%
  false-reject on genuinely-correct claims), which failed our own release threshold. So we ship it as
  **ADVISORY** with the badge withheld, and the deterministic gates remain the authoritative safety layer.
  We deliberately did *not* re-tune the model against its own test set to fake a better number.
- **Latency honesty.** The single-patient live path is dominated by Model A and swings from ~45s to ~190s
  under load, so we don't claim a guaranteed ≤90s; the judged demo uses a precomputed run that loads instantly.
- **Real-cloud gremlins.** The live deploy surfaced two bugs the offline tests couldn't: a missing
  `Content-Type` header on Cloud Tasks payloads (worker 422s) and three missing Cloud Tasks OIDC IAM grants
  (enqueue 500s). Both fixed and folded back into reproducible deploy scripts.

## Accomplishments we're proud of
- A working, **fail-closed** medical-AI pipeline where deterministic code, not the LLM, owns every fact.
- A **fully deployed** GCP architecture (Scheduler → Cloud Tasks → private Cloud Run → real Gemini →
  Firestore), verified end-to-end with real patient runs persisting correct statuses.
- **Radical honesty**: measured, unflattering results (ADVISORY review, variable latency) reported as-is.

## What we learned
Adversarial verification is only as good as its measured specificity; a second model that cries wolf is a
liability, and the honest move is to demote it and lean on deterministic guarantees. And nothing substitutes
for a real deployment: the last two bugs were invisible until the system ran on real infrastructure.

## What's next
Cross-vendor Model B (true independence), a browser-facing authenticated read API, a less trigger-happy
reviewer measured against an independently-authored control set, and a live FHIR source (Cloud Healthcare API).

---

## Links (paste into Devpost)
- **Live demo (frontend):** https://chartpilot-frontend-zkhsg5lcca-el.a.run.app
- **Source code:** https://github.com/kayomarz97/chartpilot   ← *must be made PUBLIC or shared with judges (see checklist)*
- **Demo video:** https://youtu.be/wKAX3P97Ye0
- **Backend API (private, OIDC-only, not publicly visitable by design):** https://chartpilot-api-zkhsg5lcca-el.a.run.app

---

## ⚠️ REQUIRED disclosure: paste this verbatim into the Devpost description (hackathon reuse rule)
> **Reused-work disclosure.** ChartPilot reuses **design patterns and knowledge** from the author's
> pre-existing **Iatronix** platform (github.com/kayomarz97/iatronix, med.kayomarz.com): specifically the
> evidence-first "LLM as editor, never source of facts" philosophy and the medical-evidence
> throttling/citation concepts. **The ChartPilot codebase (FHIR normalization, clinical validity engine,
> deterministic rules, citation verifier, blinded Model-B harness, durable orchestration, two-phase
> Firestore commit, and the entire UI) was written new during the submission period.** Full per-component
> attribution is in `ATTRIBUTION.md` and `README.md` in the repository.

## Honest scope note (recommended to include, it reads as integrity, not weakness)
> Synthetic data only; not a medical device; not clinically validated. Evidence is US-FDA-jurisdiction
> labels + PubMed abstracts + a clearly-labelled placeholder guideline pack. The independent-review model
> currently ships ADVISORY (measured specificity below our release threshold); the deterministic gates are
> the authoritative safety layer.

---

## FINAL CHECKLIST: what only you can do
1. [x] **GitHub repo is public:** `https://github.com/kayomarz97/chartpilot` is public (verified — judges can
       open it). History scanned: no secret was ever committed; `.env` is gitignored and untracked.
2. [x] **Live-demo URL filled:** `https://chartpilot-frontend-zkhsg5lcca-el.a.run.app` (paste into the Devpost live-demo field).
3. [x] **Demo video recorded & linked:** `https://youtu.be/wKAX3P97Ye0` (also embedded in `README.md`).
4. [ ] **Rotate the Gemini API key** (it was shared in plain text during setup). New key in Google AI Studio,
       then update Secret Manager:
       `gcloud secrets versions add gemini-api-key --project=chartpilot-agentic --data-file=-`
       (run in your OWN terminal, paste the new key, Ctrl-D), then redeploy is not required: Cloud Run reads
       `:latest` on the next revision; to pick it up now: `gcloud run services update chartpilot-api --region=asia-south1 --project=chartpilot-agentic` (no-op redeploy).
5. [ ] **Submit on Devpost before 2026-08-31, 5:00 pm PDT** (Taskmaster track). Double-check the reuse
       disclosure is in the description.
