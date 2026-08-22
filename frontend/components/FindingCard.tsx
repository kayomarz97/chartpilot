import type { Finding } from "@/lib/types";
import { SeverityBadge } from "./SeverityBadge";
import { VerdictBadge } from "./VerdictBadge";
import { ClaimTypeBadge } from "./ClaimTypeBadge";
import { ShapeIcon } from "./icons";
import { ClinicianActionControl } from "./ClinicianActionControl";
import styles from "./FindingCard.module.css";

export function FindingCard({
  finding,
  patientId,
  onViewEvidence,
}: {
  finding: Finding;
  /** Threaded down so the clinician-label control can build a stable,
   * per-patient-per-claim idempotency key (Phase B, spec §53). */
  patientId: string;
  onViewEvidence: (finding: Finding) => void;
}) {
  return (
    <article className={styles.card} data-severity={finding.severity ?? "NONE"}>
      <div className={styles.badgeRow}>
        <SeverityBadge severity={finding.severity} />
        <VerdictBadge verdict={finding.verdict} />
        <ClaimTypeBadge claimType={finding.claimType} />
      </div>

      <h3 className={styles.statement}>{finding.statement}</h3>

      <div className={styles.section}>
        <div className={styles.sectionLabel}>Rationale</div>
        <p className={styles.text}>{finding.rationale}</p>
      </div>

      <div className={styles.section}>
        <div className={styles.sectionLabel}>Recommended action</div>
        <p className={styles.text}>{finding.recommendedAction}</p>
      </div>

      {finding.patientEvidence.length > 0 && (
        <div className={styles.section}>
          <div className={styles.sectionLabel}>Supporting chart evidence</div>
          <ul className={styles.evidenceList}>
            {finding.patientEvidence.map((pe, i) => (
              <li key={i} className={styles.evidenceItem}>
                <span className={styles.evidenceItemLabel}>{pe.label}:</span> {pe.detail}
              </li>
            ))}
          </ul>
        </div>
      )}

      {finding.externalEvidence.length > 0 && (
        <div className={styles.actions}>
          <button
            type="button"
            className={styles.viewEvidenceButton}
            onClick={() => onViewEvidence(finding)}
          >
            <ShapeIcon shape="square" />
            View evidence ({finding.externalEvidence.length})
          </button>
        </div>
      )}

      <ClinicianActionControl
        patientId={patientId}
        claimId={finding.claimId}
        verdictShown={finding.verdict}
      />
    </article>
  );
}
