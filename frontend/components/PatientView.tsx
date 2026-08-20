"use client";

import { useState } from "react";
import Link from "next/link";
import type { Finding, PatientRun } from "@/lib/types";
import { isErrorStatus, sortFindingsBySeverity } from "@/lib/types";
import { StatusBadge } from "./StatusBadge";
import { FindingCard } from "./FindingCard";
import { EvidenceDrawer } from "./EvidenceDrawer";
import { EmptyState } from "./EmptyState";
import { ErrorState } from "./ErrorState";
import { Timeline } from "./Timeline";
import styles from "./PatientView.module.css";

export function PatientView({ patient }: { patient: PatientRun }) {
  const [activeFinding, setActiveFinding] = useState<Finding | null>(null);
  const showError = isErrorStatus(patient.status);
  const findings = sortFindingsBySeverity(patient.findings);

  return (
    <div className={`container ${styles.page}`}>
      <Link href="/" className={styles.backLink}>
        &larr; Back to patient list
      </Link>

      <div>
        <div className={styles.patientHeader}>
          <h1 className={styles.patientName}>{patient.patientName}</h1>
          <StatusBadge status={patient.status} />
        </div>
        <p className={styles.patientMeta}>{patient.patientId}</p>
        <p className={styles.stage}>Stage: {patient.stage}</p>
      </div>

      {showError ? (
        <ErrorState status={patient.status} stage={patient.stage} />
      ) : (
        <section aria-labelledby="findings-heading">
          <h2 id="findings-heading" className={styles.sectionHeading}>
            Findings
          </h2>
          {findings.length === 0 ? (
            <EmptyState />
          ) : (
            <ul className={styles.findingsList}>
              {findings.map((finding) => (
                <li key={finding.claimId}>
                  <FindingCard finding={finding} onViewEvidence={setActiveFinding} />
                </li>
              ))}
            </ul>
          )}
        </section>
      )}

      <section aria-labelledby="timeline-heading">
        <h2 id="timeline-heading" className={styles.sectionHeading}>
          Timeline
        </h2>
        <Timeline events={patient.timeline} />
      </section>

      <EvidenceDrawer finding={activeFinding} onClose={() => setActiveFinding(null)} />
    </div>
  );
}
