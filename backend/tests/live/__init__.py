"""The live-integration layer (spec §23): tests that call the REAL Gemini API.

Everything in this package is marked `pytest.mark.live` and is excluded from
the default `pytest tests` collection (`addopts = "... -m \"not live\""` in
`pyproject.toml`), so `make check` never spends real tokens or touches the
network. See `README.md` in this directory for how to run these tests on
purpose.
"""

from __future__ import annotations
