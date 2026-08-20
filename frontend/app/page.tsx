import { patients } from "@/lib/mockData";
import { PatientCard } from "@/components/PatientCard";
import styles from "./page.module.css";

export default function DashboardPage() {
  return (
    <div className={`container ${styles.page}`}>
      <h1 className={styles.title}>Patients queued for review</h1>
      <p className={styles.subtitle}>
        Charts prepared ahead of today&apos;s visits. Select a patient to review identified findings.
      </p>
      <ul className={styles.grid} aria-label="Patient list">
        {patients.map((patient) => (
          <li key={patient.runId}>
            <PatientCard patient={patient} />
          </li>
        ))}
      </ul>
    </div>
  );
}
