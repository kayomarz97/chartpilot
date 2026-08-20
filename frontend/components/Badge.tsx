import styles from "./Badge.module.css";
import { ShapeIcon, type IconShape } from "./icons";

export type BadgeVariant =
  | "critical"
  | "high"
  | "moderate"
  | "low"
  | "info"
  | "verified"
  | "review"
  | "rejected"
  | "failed"
  | "queued";

/**
 * Base badge: every status/severity/verdict signal in the app renders through
 * this component so color is NEVER the only carrier of meaning — a shape
 * icon and an uppercase text label always accompany it (spec §57A).
 */
export function Badge({
  variant,
  shape,
  label,
  className,
}: {
  variant: BadgeVariant;
  shape: IconShape;
  label: string;
  className?: string;
}) {
  return (
    <span className={`${styles.badge} ${styles[variant]} ${className ?? ""}`}>
      <ShapeIcon shape={shape} />
      {label}
    </span>
  );
}
