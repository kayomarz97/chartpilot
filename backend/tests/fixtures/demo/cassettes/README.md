# Demo cassettes

These `patient_*.json` files are **hand-authored** Gemini response cassettes,
NOT live recordings. Each drives the hermetic `FakeGeminiClient`
(`tests/support/fake_gemini.py`) used by `tests/unit/test_pipeline_demo.py`
and `tests/adversarial/test_prompt_injection_invariant.py` so those tests can
run the full pipeline deterministically with zero network access.

Each file carries a `"_meta"` object documenting what real model/date this
hand-authored content is meant to be consistent with:

```json
"_meta": {
  "model_a_id": "gemini-3.7-flash",
  "model_b_id": "gemini-3.5-flash",
  "recorded_at": "2026-08-20",
  "note": "hand-authored cassette consistent with the demo fixtures; not a live recording"
}
```

`_meta` is documentation only — the loaders (`_model_a_client`/`_model_b_client`
helpers in the tests above) read only the `model_a`/`model_b` keys and
ignore `_meta` entirely, so it never affects test behavior.

For an actual live recording against the real API (spec §23), see
`tests/live/` — a separate, explicitly-marked, non-hermetic layer excluded
from `make check`.
