import type { PatientRun } from "./types";
import { isErrorStatus } from "./types";

// TD-011: live backend wiring. The dashboard/patient pages always render
// instantly from the bundled demo data (lib/mockData.ts) and only swap in
// live data if this fetch succeeds — the site must never be broken by a
// missing or unreachable backend.

/** Backend run this demo UI displays. Change here to point at a different run. */
export const RUN_ID = "demo";

/** Same-origin proxy: the browser calls the frontend's own /api/runs route
 * handler, which authenticates to the PRIVATE backend server-side (see
 * app/api/runs/route.ts). The browser never talks to the backend directly. */
const RUNS_PROXY_PATH = "/api/runs";

const FETCH_TIMEOUT_MS = 3000;

interface RunResponse {
  run_id: string;
  generated_at: string;
  patients: PatientRun[];
}

function isValidRunResponse(data: unknown): data is RunResponse {
  if (
    typeof data !== "object" ||
    data === null ||
    !Array.isArray((data as RunResponse).patients) ||
    (data as RunResponse).patients.length === 0
  ) {
    return false;
  }
  // Only treat the live run as usable if at least one patient completed
  // successfully. If EVERY patient is an error status (e.g. the whole run
  // failed because the Gemini spend cap was hit), fall back to the bundled
  // demo data rather than render a wall of error cards.
  return (data as RunResponse).patients.some((p) => !isErrorStatus(p.status));
}

/**
 * Attempts to fetch the live patient run from the backend. Returns null on
 * any failure whatsoever — unset base URL, network error, non-2xx, timeout,
 * malformed body, or an empty patient list — so callers can always fall
 * back to the bundled demo data without ever surfacing a broken page.
 */
export async function fetchLivePatients(): Promise<PatientRun[] | null> {
  const controller = new AbortController();
  const timeoutId = setTimeout(() => controller.abort(), FETCH_TIMEOUT_MS);

  try {
    const res = await fetch(RUNS_PROXY_PATH, {
      signal: controller.signal,
      cache: "no-store",
    });
    if (!res.ok) return null;

    const data: unknown = await res.json();
    if (!isValidRunResponse(data)) return null;

    return data.patients;
  } catch {
    // Network error, timeout/abort, or JSON parse failure — all treated
    // the same: fall back to demo data.
    return null;
  } finally {
    clearTimeout(timeoutId);
  }
}
