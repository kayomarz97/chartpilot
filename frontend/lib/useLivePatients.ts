"use client";

import { useEffect, useState } from "react";
import type { PatientRun } from "./types";
import { fetchLivePatients } from "./liveData";

export type DataSource = "live" | "demo";

/**
 * Renders `fallback` (the bundled demo data) immediately and synchronously,
 * then attempts to swap in the live backend run after mount. Never blocks
 * first paint and never leaves the page in a loading/broken state — on any
 * fetch failure it silently keeps the fallback data.
 */
export function useLivePatients(fallback: PatientRun[]): {
  patients: PatientRun[];
  source: DataSource;
} {
  const [state, setState] = useState<{ patients: PatientRun[]; source: DataSource }>({
    patients: fallback,
    source: "demo",
  });

  useEffect(() => {
    let cancelled = false;
    fetchLivePatients().then((live) => {
      if (cancelled || !live) return;
      setState({ patients: live, source: "live" });
    });
    return () => {
      cancelled = true;
    };
    // Intentionally run once on mount only — `fallback` is only used as the
    // initial render value, refetching on every fallback identity change
    // would defeat the "fetch once, swap if available" contract.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  return state;
}
