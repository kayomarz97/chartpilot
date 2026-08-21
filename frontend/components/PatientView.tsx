"use client";

import { useState } from "react";
import Link from "next/link";
import type { Finding, PatientRun } from "@/lib/types";
import { isErrorStatus, sortFindingsBySeverity } from "@/lib/types";
import type { DataSource } from "@/lib/useLivePatients";
import { StatusBadge } from "./StatusBadge";
import { DataSourceBadge } from "./DataSourceBadge";
import { FindingCard } from "./FindingCard";
import { EvidenceDrawer } from "./EvidenceDrawer";
import { EmptyState } from "./EmptyState";
import { ErrorState } from "./ErrorState";
import { ManualReviewPanel } from "./ManualReviewPanel";
import styles from "./PatientView.module.css";

export function PatientView({
  patient,
  dataSource,
}: {
  patient: PatientRun;
  /** Present only when the page attempted a live-backend fetch (TD-011); omitted in unit tests. */
  dataSource?: DataSource;
}) {
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
          {dataSource && <DataSourceBadge source={dataSource} />}
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

      <ManualReviewPanel timeline={patient.timeline} labs={patient.labs} />

      <EvidenceDrawer finding={activeFinding} onClose={() => setActiveFinding(null)} />
    </div>
  );
}
