import type { RunStatus } from "@/lib/types";
import { ShapeIcon } from "./icons";
import styles from "./ErrorState.module.css";

const STATUS_COPY: Record<string, { label: string; detail: string }> = {
  FAILED: {
    label: "Processing error",
    detail:
      "An error occurred while preparing this chart. The available data could not be fully processed, and no findings could be reliably identified.",
  },
  TIMED_OUT: {
    label: "Processing timed out",
    detail:
      "Chart preparation did not complete within the allotted time. The available data could not be fully processed, and no findings could be reliably identified.",
  },
  DEAD_LETTER: {
    label: "Processing failed permanently",
    detail:
      "This run failed after repeated retries and has been routed for manual handling. No automated findings are available for this chart.",
  },
};

/**
 * Distinct, unmistakable failure panel — never conflated with EmptyState.
 * Used for FAILED / TIMED_OUT / DEAD_LETTER runs.
 *
 * Carries a labeled "safety demonstration" banner so this reads as an
 * intentional product feature (ChartPilot always surfaces failures loudly,
 * never a silent "no findings") rather than as a bug in the demo.
 */
export function ErrorState({ status, stage }: { status: RunStatus; stage: string }) {
  const copy = STATUS_COPY[status] ?? STATUS_COPY.FAILED!;
  return (
    <div className={styles.outer}>
      <p className={styles.demoBanner}>
        <ShapeIcon shape="help-circle" />
        Safety demonstration — how ChartPilot surfaces failures (never a silent &quot;no findings&quot;)
      </p>
      <div className={styles.wrap} role="alert">
        <div className={styles.head}>
          <ShapeIcon shape="octagon" className={styles.icon} />
          <h2 className={styles.title}>{copy.label} — manual review required</h2>
        </div>
        <p className={styles.body}>
          This chart could not be safely prepared. {copy.detail} Please review the source chart
          directly before this visit.
        </p>
        <p className={styles.meta}>Last stage reached: {stage}</p>
      </div>
    </div>
  );
}
