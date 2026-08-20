import Link from "next/link";
import type { PatientRun } from "@/lib/types";
import { summarizePatient } from "@/lib/summary";
import { StatusBadge } from "./StatusBadge";
import styles from "./PatientCard.module.css";

export function PatientCard({ patient }: { patient: PatientRun }) {
  return (
    <Link href={`/patients/${patient.patientId}`} className={styles.card}>
      <div className={styles.row}>
        <div>
          <div className={styles.name}>{patient.patientName}</div>
          <div className={styles.id}>{patient.patientId}</div>
        </div>
        <StatusBadge status={patient.status} />
      </div>
      <div className={styles.summary}>{summarizePatient(patient)}</div>
    </Link>
  );
}
