"""Helper library for the accelerated 4-round self-improving live run.

Everything here is a pure/importable helper shared by the CLI scripts in
`scripts/` (`gen_patients.py`, `live_round.py`, `improve_round.py`,
`live_run_report.py`). Nothing in this package performs network I/O or reads
`app.config.Settings` itself -- that stays in the CLI scripts, which are the
only places that need the ambient-key hazard guard (see each script's module
docstring). This package is NOT part of the `backend/app` tree and is not
covered by `make check`'s ruff/mypy scope (both are configured to run from
`backend/`) -- see `ARCHITECTURE.md`/the Makefile for that scoping.
"""

from __future__ import annotations
