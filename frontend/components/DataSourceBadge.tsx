import type { DataSource } from "@/lib/useLivePatients";
import { ShapeIcon } from "./icons";
import styles from "./DataSourceBadge.module.css";

/**
 * Small indicator of whether the page is showing a live backend run
 * (TD-011) or the bundled fallback demo data — shown whenever a live fetch
 * was attempted, so it's always clear which one the clinician is looking at.
 */
export function DataSourceBadge({ source }: { source: DataSource }) {
  const isLive = source === "live";
  return (
    <span className={`${styles.badge} ${isLive ? styles.live : styles.demo}`}>
      <ShapeIcon shape={isLive ? "check-circle" : "clock"} />
      {isLive ? "Live data" : "Demo data (offline)"}
    </span>
  );
}
