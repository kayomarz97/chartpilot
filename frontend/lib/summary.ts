import { isErrorStatus, type PatientRun, type Severity } from "./types";

const SEVERITY_LABEL: Record<Exclude<Severity, null>, string> = {
  CRITICAL: "critical",
  HIGH: "high-priority",
  MODERATE: "moderate",
  LOW: "low-priority",
  INFO: "informational",
};

const SEVERITY_RANK: Record<Exclude<Severity, null>, number> = {
  CRITICAL: 0,
  HIGH: 1,
  MODERATE: 2,
  LOW: 3,
  INFO: 4,
};

/** Short dashboard-card summary line for a patient run. */
export function summarizePatient(run: PatientRun): string {
  if (isErrorStatus(run.status)) {
    return "Processing error";
  }
  if (run.findings.length === 0) {
    return "No high-priority findings";
  }
  let topSeverity: Exclude<Severity, null> | null = null;
  for (const f of run.findings) {
    if (f.severity === null) continue;
    if (topSeverity === null || SEVERITY_RANK[f.severity] < SEVERITY_RANK[topSeverity]) {
      topSeverity = f.severity;
    }
  }
  if (topSeverity === null) {
    return `${run.findings.length} finding${run.findings.length === 1 ? "" : "s"} identified`;
  }
  const count = run.findings.filter((f) => f.severity === topSeverity).length;
  const label = SEVERITY_LABEL[topSeverity];
  return `${count} ${label} finding${count === 1 ? "" : "s"} identified`;
}
