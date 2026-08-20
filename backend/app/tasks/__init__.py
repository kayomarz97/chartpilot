"""Durable orchestration for per-patient nightly runs (spec §45/§45B/§46/§47/§48).

This package is fully hermetic: everything that would talk to a real
external system (Cloud Tasks, Firestore, Cloud Scheduler) is expressed as a
`Protocol` with an in-memory fake implementation. Real GCP-backed adapters
and HTTP endpoints are a later phase; nothing here performs network I/O.
"""

from __future__ import annotations
