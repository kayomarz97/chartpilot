"""Firestore-backed persistence + §45A two-phase atomic finalization (spec §44/§45A).

`app.storage.repository.RunRepository` is the persistence boundary: a `Protocol`
implemented by `app.storage.inmemory.InMemoryRunRepository` (the hermetic fake used
in tests and, for now, the orchestrator) and `app.storage.firestore_repo.FirestoreRunRepository`
(the thin real adapter over the Firestore Admin SDK, wired up live at Phase 18).

`app.storage.two_phase.finalize_patient_result` is the heart of this package: it writes
a patient's claims/evidence artifacts to their subcollections and only then flips the
patient summary's `commit_status` to COMMITTED -- so a crash between artifact writes and
the terminal-status commit can never be observed as a COMPLETED run (spec §45A).
"""

from __future__ import annotations
