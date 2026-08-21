"""HTTP API surface for Cloud Scheduler / Cloud Tasks callers (spec §76A.1).

`auth.py` verifies Google-signed OIDC bearer tokens; `routes.py` mounts the
two endpoints those callers invoke (`POST /enqueue-run`,
`POST /tasks/process-patient`) on `app.main:app`. Everything that would talk
to a real GCP service is injectable so the hermetic test suite never touches
the network.
"""

from __future__ import annotations
