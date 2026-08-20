"""Phase 14: the end-to-end demo pipeline chaining every prior phase.

`app.pipeline.runner.run_patient` fetches one patient's FHIR bundle,
normalizes it, evaluates the K_HIGH_RISK_001 safety rule and the derived-
metric validity engine, reasons over it with Model A, checks citations,
runs the blinded independent review (Model B) behind the deterministic
layer, applies the final claim gate, and persists the result -- exactly the
chain spec'd across Phases 3-13, wired together for the first time here.
"""

from __future__ import annotations
