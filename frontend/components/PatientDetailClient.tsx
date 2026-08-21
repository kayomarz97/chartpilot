"use client";

import { useMemo } from "react";
import type { DataSource } from "@/lib/useLivePatients";
import { useLivePatients } from "@/lib/useLivePatients";
import type { PatientRun } from "@/lib/types";
import { PatientView } from "./PatientView";

/**
 * Client-side data resolution for a single patient page (TD-011). The
 * server component already resolved a safe fallback patient from the
 * bundled mock data (and 404s up front for genuinely unknown ids); this
 * component then attempts to swap in the matching patient from the live
 * backend run, keeping the fallback if the live fetch fails or doesn't
 * include this patient.
 */
export function PatientDetailClient({
  patientId,
  fallback,
}: {
  patientId: string;
  fallback: PatientRun;
}) {
  const { patients, source } = useLivePatients([fallback]);
  const livePatient = useMemo(
    () => patients.find((p) => p.patientId === patientId),
    [patients, patientId]
  );

  const patient = livePatient ?? fallback;
  const dataSource: DataSource = livePatient && source === "live" ? "live" : "demo";

  return <PatientView patient={patient} dataSource={dataSource} />;
}
