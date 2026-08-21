"use client";

import { patients as mockPatients } from "@/lib/mockData";
import { isErrorStatus } from "@/lib/types";
import { useLivePatients } from "@/lib/useLivePatients";
import { PatientCard } from "@/components/PatientCard";
import { DataSourceBadge } from "@/components/DataSourceBadge";
import styles from "./page.module.css";

export default function DashboardPage() {
  const { patients, source } = useLivePatients(mockPatients);
  const normalPatients = patients.filter((p) => !isErrorStatus(p.status));
  const errorPatients = patients.filter((p) => isErrorStatus(p.status));

  return (
    <div className={`container ${styles.page}`}>
      <div className={styles.titleRow}>
        <div>
          <h1 className={styles.title}>Patients queued for review</h1>
          <p className={styles.subtitle}>
            Charts prepared ahead of today&apos;s visits. Select a patient to review identified findings.
          </p>
        </div>
        <DataSourceBadge source={source} />
      </div>

      <ul className={styles.grid} aria-label="Patient list">
        {normalPatients.map((patient) => (
          <li key={patient.runId}>
            <PatientCard patient={patient} />
          </li>
        ))}
      </ul>

      {errorPatients.length > 0 && (
        <section className={styles.safetyDemo} aria-labelledby="safety-demo-heading">
          <h2 id="safety-demo-heading" className={styles.safetyDemoHeading}>
            Safety demonstration — how ChartPilot surfaces failures (never a silent &quot;no findings&quot;)
          </h2>
          <p className={styles.safetyDemoBody}>
            The chart below intentionally failed to process. It demonstrates that ChartPilot always
            surfaces a processing failure with a distinct, unmistakable error state — it never falls
            back to an empty findings list that could be mistaken for a clean chart.
          </p>
          <ul className={styles.grid} aria-label="Safety demonstration patient list">
            {errorPatients.map((patient) => (
              <li key={patient.runId}>
                <PatientCard patient={patient} />
              </li>
            ))}
          </ul>
        </section>
      )}
    </div>
  );
}
