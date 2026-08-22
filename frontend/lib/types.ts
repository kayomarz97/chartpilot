// Domain model for ChartPilot — mirrors the backend's processed-run schema.
// This is the single source of truth for shapes consumed by the UI.

export type RunStatus =
  | "QUEUED"
  | "RUNNING"
  | "COMPLETED"
  | "PARTIAL"
  | "FLAGGED_FOR_REVIEW"
  | "FAILED"
  | "TIMED_OUT"
  | "DEAD_LETTER";

/** Statuses that must render the distinct ErrorState instead of a findings list. */
export const ERROR_STATUSES: ReadonlySet<RunStatus> = new Set([
  "FAILED",
  "TIMED_OUT",
  "DEAD_LETTER",
]);

export type ClaimType =
  | "PATIENT_FACT"
  | "REGULATORY_FACT"
  | "GUIDELINE_RECOMMENDATION"
  | "PATIENT_SPECIFIC_INFERENCE"
  | "POSSIBLE_CONCERN"
  | "CLINICIAN_REVIEW_SUGGESTION"
  | "UNCERTAINTY";

export type Severity = "CRITICAL" | "HIGH" | "MODERATE" | "LOW" | "INFO" | null;

export type Verdict =
  | "VERIFIED"
  | "PARTIALLY_VERIFIED"
  | "CONFLICTING"
  | "UNVERIFIABLE"
  | "REJECTED"
  | "REQUIRES_REVIEW";

export type EvidenceTier = "REGULATORY_LABEL" | "LITERATURE" | "GUIDELINE";

export type CitationVerdict = "VERIFIED_SPAN" | "REJECT" | "FLAG_FOR_REVIEW";

export interface GateResult {
  gate: string;
  passed: boolean;
}

export interface ExternalEvidence {
  evidenceId: string;
  tier: EvidenceTier;
  publisher: string;
  jurisdiction: string;
  publicationDate: string;
  version: string;
  sourceUrl: string;
  snapshotId: string;
  verbatimSpan: string;
  computedStartOffset: number;
  computedEndOffset: number;
  citationVerdict: CitationVerdict;
  gatesPassed: GateResult[];
  modelBFinding: string;
  modelBShouldReject: boolean;
  /** Clinician identifier/status, or null/"PENDING" if not yet reviewed. */
  reviewedBy: string | null;
}

export interface PatientEvidenceRef {
  label: string;
  detail: string;
}

/** A clinician's ground-truth label on one finding (Phase B, spec §53) —
 * the outer self-improving loop's training signal. */
export type ClinicianActionKind = "CONFIRM" | "OVERRIDE" | "CORRECT";

export interface Finding {
  claimId: string;
  claimType: ClaimType;
  statement: string;
  severity: Severity;
  verdict: Verdict;
  /** How many times the Phase A "gate-failure → revise → retry" loop
   * successfully swapped in a re-quoted claim; 0 if it never entered the
   * loop. Informational only — never affects `verdict`. */
  revisionAttempts: number;
  rationale: string;
  recommendedAction: string;
  patientEvidence: PatientEvidenceRef[];
  externalEvidence: ExternalEvidence[];
}

export type TimelineEventKind =
  | "LAB"
  | "MEDICATION"
  | "DIAGNOSIS"
  | "ENCOUNTER"
  | "ADVERSE_EVENT"
  | "PROCEDURE";

export interface TimelineEvent {
  date: string;
  kind: TimelineEventKind;
  label: string;
  detail: string;
  severity?: Severity;
}

/** Flag on a single lab result relative to its reference range, or null if within range. */
export type LabFlag = "HIGH" | "LOW" | "CRITICAL" | null;

export interface LabPoint {
  date: string;
  value: number;
  flag?: LabFlag;
}

/** A single analyte's result history — the basis for the manual-review trend sparklines. */
export interface LabTrend {
  analyte: string;
  unit: string;
  points: LabPoint[];
}

export interface PatientRun {
  runId: string;
  patientId: string;
  patientName: string;
  status: RunStatus;
  stage: string;
  findings: Finding[];
  timeline: TimelineEvent[];
  labs: LabTrend[];
}

export function isErrorStatus(status: RunStatus): boolean {
  return ERROR_STATUSES.has(status);
}

const SEVERITY_ORDER: Record<Exclude<Severity, null>, number> = {
  CRITICAL: 0,
  HIGH: 1,
  MODERATE: 2,
  LOW: 3,
  INFO: 4,
};

/** Sort findings by clinical severity, most urgent first; null severity sorts last. */
export function sortFindingsBySeverity(findings: Finding[]): Finding[] {
  return [...findings].sort((a, b) => {
    const aRank = a.severity ? SEVERITY_ORDER[a.severity] : 99;
    const bRank = b.severity ? SEVERITY_ORDER[b.severity] : 99;
    return aRank - bRank;
  });
}
