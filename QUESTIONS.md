# QUESTIONS.md — doctor_helper

Only questions whose answers materially change the build (§7). Trivial choices are decided and logged,
not asked.

## Answered (2026-08-20)
- **Reuse Iatronix?** YES — reuse where it fits, with mandatory abundant disclosure everywhere
  (hackathon rule). → TD-001, ATTRIBUTION.md.
- **GCP project?** NEW, fully isolated project; existing projects must not be affected. → TD-002.

## Pending (blocking PLAN.md finalization)

### Q1 — Hackathon identity, deadline, and scope posture
Which hackathon is this (name/URL), and what is the deadline? This decides how aggressively to scope.
The full spec is ~20 phases (weeks of work); a judged demo (§50) needs a narrow, polished vertical slice.
- Need: the hackathon name so I can research its exact rules (Taskmaster track, reuse-disclosure rule
  text, judging rubric), and the deadline so I can plan MVP vs full-spec.

### Q2 — Gemini access path + Model A/B split
Proposed: **Model A = Gemini** (primary reasoning, per spec), **Model B = Claude** (independent
adversarial reviewer — genuine cross-vendor blinding, §21.4). How will we access Gemini under the NEW
project — Google AI Studio API key, or Vertex AI? And is Claude access available for Model B?

### Q3 — New GCP project: region + billing readiness
Which region, and is billing set up for a new project? If billing isn't ready, I'll keep the demo on
free-tier AI Studio Gemini + local FHIR fixtures and defer paid GCP (Cloud Run/Tasks/Firestore) until
it is — without blocking progress.
