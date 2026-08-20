import { ShapeIcon } from "./icons";
import styles from "./EmptyState.module.css";

/**
 * Deliberately calm and specific — never claims the chart is "safe" or
 * "all clear" (spec §60/§61); it only states what was and wasn't found.
 */
export function EmptyState() {
  return (
    <div className={styles.wrap} role="status">
      <ShapeIcon shape="check-circle" className={styles.icon} />
      <h2 className={styles.title}>No high-priority findings identified</h2>
      <p className={styles.body}>
        Automated review of this chart did not identify findings that meet the threshold for
        flagging. This does not replace clinician judgment during the visit.
      </p>
    </div>
  );
}
