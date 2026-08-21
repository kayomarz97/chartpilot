# ChartPilot — Pre-Clinic Chart-Prep Agent

> **⚠️ Synthetic data only. Not a medical device. Not clinically validated. Not for clinical use.**
> ChartPilot is a hackathon prototype (All Things Agentic, Taskmaster track). It runs entirely on
> hand-authored **synthetic** FHIR data and makes **no** claim of clinical validation, regulatory
> approval, HIPAA compliance, or production readiness.

**🔗 Live demo (public UI):** https://chartpilot-frontend-zkhsg5lcca-el.a.run.app
**🔗 Backend API (private, OIDC-only by design):** https://chartpilot-api-zkhsg5lcca-el.a.run.app
**🔗 Source:** https://github.com/kayomarz97/chartpilot · **Demo video:** _(add link)_

---

## 30-second version (plain language)

Before a clinic visit, a doctor has a couple of minutes to skim a patient's chart, and it is easy to
miss something that matters — a dangerously high potassium in someone on a blood-pressure drug that
pushes potassium higher, a lab trend nobody followed up. **ChartPilot reads the whole chart the night
before and prepares a one-page safety brief** — and, crucially, it *shows its work*: every point it
raises comes with the exact source it is based on, and a **second AI** has already tried to prove that
point wrong before you ever see it. If anything is uncertain, it says so and hands it to the clinician.
It never quietly makes something up, and it never hides a failure behind "nothing found."

## The thesis (technical)

Most "AI + health" demos are `FHIR → LLM → advice`. That is exactly the pattern you must **not** ship in
medicine. ChartPilot implements a safer one (`SPEC.md §85`):

> **FHIR facts + deterministic clinical computation + current medical evidence + patient-history
> reasoning + independent adversarial verification + clinician review** — *not* `FHIR → LLM → advice`.

Deterministic code owns every fact; the LLM is only an *editor/synthesizer*; an evidence + citation layer
forbids unsupported claims; a **blinded** second model tries to break the first's claims; and a final gate
**fails closed** — an unproven claim can never be shown as verified. **The clinician remains the
decision-maker.**

---

## 🏆 Why this should win (highlights)

1. **It is genuinely agentic *and* genuinely safe.** The agent autonomously fetches, computes, retrieves
   evidence, reasons, self-checks with a second model, and persists — but safety comes from deterministic
   guarantees, not from trusting the model. This is the hard version of the problem, done honestly.
2. **Adversarial self-verification that we actually measured — and reported honestly.** A blinded Model B
   tries to *falsify* every claim. We measured it against a corruption suite, found it **over-aggressive**
   (75% false-reject), and therefore **ship it as ADVISORY with the badge withheld** rather than fake a
   better number. Measured honesty is the differentiator.
3. **Fails closed, provably.** A prompt-injection invariant test proves free text can never alter a
   normalized fact, a rule, or a gate (byte-equal, no-exception). Failures surface as
   `FAILED`/`FLAGGED_FOR_REVIEW`, **never** as a silent "no findings."
4. **Fully deployed, end-to-end, on real cloud** — Scheduler → Cloud Tasks → private Cloud Run → **real
   Gemini** → Firestore → a public UI that reads the **real** results back. Not a mock.
5. **The build process is itself a submission-worthy artifact** — a 20-phase protocol with
   machine-checkable gates, a persistent decision log, and one commit per tested checkpoint. See
   *"Built with AI agents, visibly"* below.
6. **Radical transparency about scope.** Synthetic data, US-label jurisdiction, ADVISORY review,
   variable latency — all stated up front (`SPEC §79`). Integrity reads as strength, not weakness.

---

## 🔁 Reused-work disclosure (hackathon rule)

Per the rule *"Projects must be newly created during the Submission Period … but must disclose any other
pre-existing code or work incorporated,"* ChartPilot reuses **design patterns and knowledge** from the
author's existing **Iatronix** platform (`github.com/kayomarz97/iatronix`, med.kayomarz.com) —
specifically the evidence-first "LLM as editor, never source of facts" philosophy, NCBI/openFDA throttling
patterns, and the grounding/citation-registry concepts. **The ChartPilot codebase (FHIR normalization,
ClinicalValidityEngine, deterministic rules, citation verifier, blinded Model-B harness + corruption
suite, durable orchestration, two-phase Firestore commit, and the entire UI) was written new during the
submission period.** See `ATTRIBUTION.md` for the authoritative per-component ledger.

---

## How it works

### In plain language, step by step
1. **Read the chart.** Pull the patient's longitudinal FHIR record (labs, meds, diagnoses, allergies).
2. **Turn it into clean facts.** Convert units, resolve which lab result is the current one, handle dates
   and time zones precisely — deterministically, in code.
3. **Apply clinical rules.** Run checks a careful clinician would (e.g. "high potassium in someone on a
   drug that raises potassium"), plus kidney-function math (eGFR).
4. **Gather current evidence.** Pull the relevant drug-label facts and published literature/guideline
   citations, and freeze an exact, tamper-evident copy.
5. **Let the AI draft findings.** Model A writes each finding *with the exact quote* from the evidence it
   relied on.
6. **Check every quote automatically.** Code verifies the quote really exists in the real source, at the
   offsets *we* computed — never offsets the model claimed.
7. **Have a second AI attack it.** A blinded Model B (which never sees Model A's reasoning) tries to prove
   each finding wrong.
8. **Refuse to pass anything unproven.** A final gate decides the verdict; disagreement → human review;
   pending-review guidance can only ever be "partially verified."
9. **Save it durably and show it.** Results are written to the database and rendered in the dashboard,
   alongside a **manual-review panel** (history + lab trends) so the clinician can cross-check the AI.

### Component flow (what runs, in order)

```mermaid
flowchart LR
  SCHED[Cloud Scheduler<br/>nightly · Asia/Kolkata] --> ENQ[Cloud Run<br/>POST /enqueue-run]
  ENQ --> TASKS[Cloud Tasks<br/>1 task / patient · idempotent]
  TASKS --> WORK[Cloud Run<br/>POST /tasks/process-patient]
  WORK --> P
  subgraph P[Per-patient pipeline · run_patient · fail-closed + checkpointed]
    direction TB
    A[FETCH<br/>FHIR read] --> B[NORMALIZE<br/>units · status/supersession · UTC+precision]
    B --> C[RULES + ClinicalValidityEngine<br/>K_HIGH_RISK_001 · eGFR CKD-EPI 2021]
    C --> D[EVIDENCE<br/>openFDA labels · PubMed literature ·<br/>PubMed guideline citations · immutable snapshot]
    D --> E[MODEL A · Gemini 3.7-flash<br/>structured claims + verbatim spans]
    E --> F[CITATION GATES 1-4<br/>source exists → hash → span found → tier/type]
    F --> G[MODEL B · Gemini 3.5-flash<br/>BLINDED · tries to falsify]
    G --> H[FINAL GATE<br/>claim verdicts · patient state · fail-closed]
  end
  H --> FS[(Firestore<br/>two-phase commit · claims/evidence · presentation read-model)]
  FS --> READ[Cloud Run<br/>GET /runs/&#123;id&#125; · public read-only]
  READ --> UI[Next.js UI · public<br/>dashboard · evidence drawer · manual-review panel]
```

### One run, as a sequence (who calls whom)

```mermaid
sequenceDiagram
  autonumber
  participant Sch as Cloud Scheduler
  participant Enq as Cloud Run /enqueue-run
  participant CT as Cloud Tasks
  participant Wk as Cloud Run /tasks/process-patient
  participant Ga as Gemini (A then B)
  participant FS as Firestore
  participant UI as Public UI

  Sch->>Enq: nightly POST (OIDC)
  Enq->>CT: one idempotent task per patient
  CT->>Wk: POST task (OIDC, Content-Type: json)
  Wk->>Wk: fetch → normalize → rules → evidence
  Wk->>Ga: Model A: draft claims + verbatim spans
  Wk->>Wk: deterministic citation gates 1–4
  Wk->>Ga: Model B (blinded): try to falsify
  Wk->>Wk: final gate → verdicts (fail closed)
  Wk->>FS: two-phase commit + presentation read-model
  UI->>FS: GET /runs/id (public read)
  UI-->>UI: render findings + manual-review panel
```

### Per-stage technical detail
| Stage | What it does | Why it's safe |
|---|---|---|
| **Normalize** | UCUM units via `Decimal`; observation status + supersession; UTC + precision-aware temporal engine (Asia/Kolkata display). | Facts are computed, not parsed by an LLM. |
| **Rules + validity** | `K_HIGH_RISK_001`; eGFR (CKD-EPI 2021), corrected calcium, anion gap via a `ClinicalValidityEngine`. | Deterministic; returns `INSUFFICIENT_DATA`/`INVALID` instead of guessing. |
| **Evidence** | openFDA SPL selection (§14), PubMed E-utilities literature, **PubMed guideline-publication-type citations** (see below); token-bucket throttle; immutable **content-hashed** snapshot. | Evidence is frozen and hash-verified; no live drift mid-run. |
| **Model A** | Gemini `3.7-flash` via the Interactions API; emits structured claims each carrying a **verbatim span**. | The model proposes; it does not get to assert facts without a quote. |
| **Citation gates 1–4** | source exists → content-hash matches → span really present → claim-type/tier consistent. **Offsets computed by us.** | A hallucinated or mis-attributed quote cannot pass. |
| **Model B** | Gemini `3.5-flash`, **blinded** (no Model-A rationale/confidence), gets the evidence *region*, tries to **falsify**. | Independent adversary; §22 corruption suite measures it. |
| **Final gate** | claim verdicts + orthogonal patient status/stage; A/B disagreement → review; PENDING guideline caps at PARTIALLY_VERIFIED. | **Fails closed:** unproven ⇒ never `VERIFIED`. |
| **Persist + read** | two-phase Firestore commit (§45A) of claims/evidence + a public **presentation** read-model. | Durable, idempotent; a failure is a status, never silence. |

---

## Safety design (why you can trust a finding)
1. **Deterministic layer owns the facts.** Free text is `trusted=False` and can never change a normalized
   fact, a rule, or a gate (`SPEC §53`; a byte-equal prompt-injection invariant test proves it).
2. **Every external claim carries a verbatim span**, verified by deterministic gates. Offsets are computed
   by us, never trusted from the model.
3. **A blinded second model** tries to *falsify* each claim; it never sees Model A's rationale/confidence.
4. **A final gate fails closed:** a claim that fails any gate can never be `VERIFIED`, even if Model B
   accepts it; disagreement → human review; PENDING guidance caps at `PARTIALLY_VERIFIED`.
5. **Durable + idempotent** per-patient execution with checkpoint/resume, budgets → `TIMED_OUT`, and
   dead-lettering; a failure surfaces as `FAILED`/`FLAGGED_FOR_REVIEW`, **never** "no findings."

The UI reinforces this: findings sit next to a **collapsible manual-review panel** (patient history +
recent labs with inline trend sparklines), and the one deliberately-failed demo patient is shown under a
labelled **"Safety demonstration"** so a reviewer can see exactly how failures surface.

---

## The deployed system (the backend, made visible)

Two Cloud Run services in the **isolated** GCP project `chartpilot-agentic` (`asia-south1`):

- **`chartpilot-api`** — private, `--no-allow-unauthenticated`. Runs the pipeline (Scheduler/Tasks call it
  with Google-signed **OIDC**), writes to Firestore, reads the Gemini key from **Secret Manager**. Exposes
  one **public, read-only** endpoint, `GET /runs/{run_id}`, that serves the *real* persisted run results.
- **`chartpilot-frontend`** — public. The Next.js dashboard fetches `GET /runs/{run_id}` and renders the
  **actual AI output** from the live pipeline (with graceful fallback to a bundled demo run if the backend
  is unreachable, so the site is never broken).

**Least privilege (`SPEC §73`):** two separate service accounts — a *runtime* identity that touches
Firestore + the secret, and an *invoker* identity that may only *call* the service. A leaked
Scheduler/Tasks config can trigger the service but never read patient data directly. All infra is scripted
(`infra/`), idempotent, and hard-pinned to `--project=chartpilot-agentic` (existing projects, incl.
Iatronix, are provably never touched).

```mermaid
flowchart TB
  subgraph proj[GCP project chartpilot-agentic · asia-south1 · ISOLATED]
    SM[Secret Manager<br/>gemini-api-key] --- API
    API[chartpilot-api · Cloud Run · PRIVATE<br/>pipeline + GET /runs/id public-read] --> FS[(Firestore Native)]
    SCH[Cloud Scheduler] -->|OIDC invoker SA| API
    Q[Cloud Tasks] -->|OIDC invoker SA| API
    API -->|runtime SA · datastore.user| FS
    FE[chartpilot-frontend · Cloud Run · PUBLIC] -->|GET /runs/id| API
  end
  User[Judge / clinician browser] --> FE
```

---

## 🤖 Built with AI agents, to make better AI agents — and the work is visible

This project was **built by an AI-agent workflow, on purpose, and the entire process is auditable in the
repo** — fitting for an "All Things Agentic" submission. The meta-point: *disciplined agent orchestration
can produce safety-critical software you can actually trust, because the process leaves evidence.*

- **Two-tier agent operating model** (`TECHNICAL_DECISIONS.md` TD-009): a planning/verifying agent
  (Opus) writes the brief and **independently re-verifies** every result; builder agents (Sonnet)
  implement. Builders never commit — the verifier does, only after re-running the checks.
- **A 20-phase build protocol with machine-checkable gates** (`SPEC §64/§65`): each phase ends only when
  `make check` (formatter + linter + `mypy --strict` + a **network-blocked** test suite + a secret
  scanner + a no-sampling-params gate) exits 0, its output is teed to `evidence/phase_NN.txt` (with git
  SHA + UTC), a dated `journal.md` entry exists, and an annotated `git tag phase-NN` is cut. **The tag is
  the recovery unit.** No artifact, no completion.
- **A persistent decision log.** `journal.md` (build log + every mistake and its fix) and
  `TECHNICAL_DECISIONS.md` (TD-001…TD-013) mean nothing is folklore — every non-obvious choice is written
  down with its rationale.
- **The process caught real bugs.** Two production bugs were invisible to the offline suite and only
  surfaced on the live deploy (a missing `Content-Type` on Cloud Tasks payloads; three missing Cloud Tasks
  OIDC IAM grants). Both were fixed **and folded back into reproducible scripts** — the audit trail shows
  exactly how.

**Want to inspect the work?** `git tag -l 'phase-*'` (checkpoints), `evidence/phase_*.txt` (the gate
output for each), `journal.md` (the narrative + mistakes ledger), `TECHNICAL_DECISIONS.md` (the why),
`.claude/plans/` (the plans written before each phase).

---

## Evidence & guidelines (and an honest note on PubMed)

- **openFDA** drug labels (US-FDA jurisdiction only), selected per §14.
- **PubMed E-utilities** literature — abstracts, **literature-tier**, never presented as a guideline.
- **PubMed guideline-publication-type citations (TD-012).** PubMed does **not** provide licensed guideline
  *text*; it indexes citations, **including to guideline publications** (publication type `Guideline`).
  ChartPilot queries that filter and surfaces the resulting **citations** (title, journal, year, PMID,
  link + abstract) as `GUIDELINE`-tier evidence marked `reviewed_by: PENDING`. Because the gate caps any
  PENDING guideline at `PARTIALLY_VERIFIED`, such a citation can **never alone** make a claim `VERIFIED`,
  and no guideline body text is copied (licensing-safe).

---

## Measured results (see `EVALUATION.md`)
- **Single-patient live latency:** ≤ 90 s is **achievable but NOT reliably met** — one session ~44–58 s
  (met), another ~125–193 s (not met), dominated by the Model A call under load. The judged demo uses a
  precomputed run (instant); the live path is real but latency-variable. Levers noted in `EVALUATION.md`.
- **Deterministic corruption blocking (Set D):** 7/7 (100%) blocked before Model B.
- **Model B model-only corruptions (Set M):** 8/8 (100%), 0 false-accept.
- **Model B specificity:** control false-reject **75% (3/4)** — over the ≤20% ceiling ⇒ **§22.3 threshold
  NOT met ⇒ the "independent review ✓" badge is WITHHELD; Model B verdicts show as ADVISORY only.** The
  deterministic gates remain the authoritative safety layer. We deliberately did **not** re-tune Model B
  against its own suite to inflate the number.
- **Accessibility:** automated axe pass (0 serious/critical); manual keyboard + greyscale pass pending.

---

## Honest scope & limitations (`SPEC §79`)
- **Synthetic data only**; no real PHI. Demo patients are hand-authored regression fixtures with realistic
  multi-year histories, **not** a statistically valid benchmark, and there is **no independent holdout**.
- **Two-model review is single-vendor** (both Gemini) — weaker than cross-vendor "independence,"
  compensated by stronger deterministic gates + the measured corruption suite, and currently shipped
  **ADVISORY**.
- **US-label jurisdiction only.** Guideline citations are PENDING clinician review by construction.
- **Not clinically validated. Not a medical device. Not production-ready.**

---

## Running it

**Backend (hermetic — no network, no key needed):**
```bash
cd backend && uv sync
cd .. && make check           # ruff + mypy(strict) + pytest(network-blocked) + secret-scan + sampling-param gate
```
**Frontend:**
```bash
cd frontend && pnpm install && pnpm run build && pnpm test   # production build + axe a11y
```
**Live single-patient path (costs real Gemini tokens):** put `GEMINI_API_KEY=...` in `backend/.env`
(gitignored), then `make live-test`. **Deploy (isolated GCP project):** the ordered, idempotent scripts in
`infra/` (see `infra/README.md`) — nothing runs against your cloud until you run them.

## Repository docs
`SPEC.md` (authoritative control document) · `PLAN.md` · `EVALUATION.md` (measured results) ·
`TECHNICAL_DECISIONS.md` (TD-001…013) · `ATTRIBUTION.md` (reuse ledger) · `SUBMISSION.md` (Devpost content)
· `journal.md` (build log + mistakes ledger) · `evidence/phase_*.txt` (per-phase machine-checked gates) ·
`infra/` (reproducible deploy) · `git tag -l 'phase-*'` (recovery checkpoints).
