"use client";

import { useMemo } from "react";
import type { DataSource } from "@/lib/useLivePatients";
import { useLivePatients } from "@/lib/useLivePatients";
import type { PatientRun } from "@/lib/types";
import { PatientView } from "./PatientView";

/**
 * Client-side data resolution for a single patient page (TD-011). The
 * server component resolves a safe fallback patient from the bundled mock
 * data when the id is one of the demo MRNs; for live-only ids (no mock
 * entry) `fallback` is null and this component renders entirely from the
 * live backend fetch instead of ever 404ing. It attempts to swap in the
 * matching patient from the live backend run, keeping the fallback if the
 * live fetch fails or doesn't include this patient.
 */
export function PatientDetailClient({
  patientId,
  fallback,
}: {
  patientId: string;
  fallback: PatientRun | null;
}) {
  const { patients, source } = useLivePatients(fallback ? [fallback] : []);
  const livePatient = useMemo(
    () => patients.find((p) => p.patientId === patientId),
    [patients, patientId]
  );

  const patient = livePatient ?? fallback;
  const dataSource: DataSource = livePatient && source === "live" ? "live" : "demo";

  // No mock fallback (live-only id) and the live fetch hasn't resolved a
  // matching patient yet (or ever) — render a placeholder instead of
  // crashing on a null patient.
  if (!patient) {
    return <p className="container">Loading patient…</p>;
  }

  return <PatientView patient={patient} dataSource={dataSource} />;
}
