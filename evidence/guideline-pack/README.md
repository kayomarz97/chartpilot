# Guideline pack

This directory is a small, **intentionally narrow, human-reviewed** set of
curated guideline excerpts (spec §12). It is loaded by
`backend/app/evidence/guideline_pack.py` into `GUIDELINE`-tier
`EvidenceRecord`s.

## Why narrow

Every file here is meant to be read and signed off by a clinician before it
is ever cited to an end user. The loader enforces a hard cap of 15 files
(`MAX_GUIDELINE_RECORDS` in `guideline_pack.py`) specifically so the pack
never grows past what a human can plausibly review. This is a deliberate
constraint, not a temporary limitation — do not raise the cap to make room
for un-reviewed content.

## File shape

Each `*.json` file in this directory must contain:

| field | meaning |
|---|---|
| `publisher` | the organization issuing the guideline |
| `title` | the guideline's title |
| `url` | canonical source URL |
| `publication_date` | the guideline's own publication date |
| `version` | the guideline's version/edition, if any |
| `excerpt` | the EXACT text later used for citation span-matching |
| `section` | which section of the guideline this excerpt is from |
| `license_status` | e.g. `"public-domain"`, `"permission-pending"` |
| `jurisdiction` | `"us_fda"` or `"not_applicable"` (see `app.evidence.models.Jurisdiction`) |
| `claim_type` | what kind of clinical claim this excerpt supports |
| `reviewed_by` | the name of the clinician who reviewed this excerpt, or the literal string `"PENDING"` if not yet reviewed |

## `reviewed_by` is load-bearing

`app.evidence.guideline_pack.is_clinician_reviewed(record)` reads this field
directly. **Automated tooling (including any agent) must never write a real
reviewer name into this field.** New/generated entries always ship with
`"reviewed_by": "PENDING"`; only a human editing the file by hand may change
it to their own name once they have actually reviewed the excerpt for
accuracy. See `evidence/REVIEW_QUEUE.md` for the current list of records
awaiting that review.

## `example_placeholder.json`

`example_placeholder.json` is a demo placeholder, not real clinical content.
Its title, publisher, and excerpt are all deliberately marked
`"DEMO PLACEHOLDER"` / `"PLACEHOLDER TEXT"` so it can never be mistaken for
reviewed guidance if it is ever rendered. It exists only to prove the loader
and citation pipeline work end-to-end before real, reviewed content is
added.
