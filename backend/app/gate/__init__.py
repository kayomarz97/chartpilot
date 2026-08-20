"""The final safety gate (spec §42/§43): claim verdicts + patient run-state.

Pure deterministic logic -- no LLM calls, no I/O. `claim_gate` folds every
upstream signal (patient-fact integrity, citation gates, Model B) into a
single `ClaimVerdict` per claim; `patient_state` folds the set of claim
verdicts plus pipeline stage/commit bookkeeping into one `PatientStatus` for
the whole run.
"""

from __future__ import annotations
