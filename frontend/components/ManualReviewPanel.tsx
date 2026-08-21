"use client";

import { useId, useState } from "react";
import type { LabFlag, LabTrend, TimelineEvent } from "@/lib/types";
import { Timeline } from "./Timeline";
import { ShapeIcon } from "./icons";
import styles from "./ManualReviewPanel.module.css";

const FLAG_LABEL: Record<Exclude<LabFlag, null>, string> = {
  HIGH: "High",
  LOW: "Low",
  CRITICAL: "Critical",
};

function flagClass(flag: LabFlag | undefined): string {
  switch (flag) {
    case "CRITICAL":
      return styles.flagCritical ?? "";
    case "HIGH":
      return styles.flagHigh ?? "";
    case "LOW":
      return styles.flagLow ?? "";
    default:
      return styles.flagNormal ?? "";
  }
}

/**
 * Hand-drawn inline SVG sparkline — no charting dependency. Plots each
 * point's value against its position in the series, marks the latest point
 * larger and colored by its flag, and exposes the full series as text via
 * aria-label since the shape itself conveys nothing to screen readers.
 */
function Sparkline({ trend }: { trend: LabTrend }) {
  const { points, analyte, unit } = trend;
  if (points.length === 0) return null;

  const width = 120;
  const height = 32;
  const pad = 5;
  const values = points.map((p) => p.value);
  const min = Math.min(...values);
  const max = Math.max(...values);
  const range = max - min || 1;

  const coords = points.map((p, i) => {
    const x = points.length === 1 ? width / 2 : pad + (i / (points.length - 1)) * (width - pad * 2);
    const y = height - pad - ((p.value - min) / range) * (height - pad * 2);
    return { x, y, point: p };
  });

  const polylinePoints = coords.map((c) => `${c.x.toFixed(1)},${c.y.toFixed(1)}`).join(" ");
  const lastIndex = coords.length - 1;
  const seriesDescription = points
    .map((p) => `${p.value} ${unit} on ${p.date}${p.flag ? ` (${FLAG_LABEL[p.flag]})` : ""}`)
    .join("; ");

  return (
    <svg
      className={styles.sparkline}
      width={width}
      height={height}
      viewBox={`0 0 ${width} ${height}`}
      role="img"
      aria-label={`${analyte} trend: ${seriesDescription}`}
    >
      {coords.length > 1 && (
        <polyline
          points={polylinePoints}
          fill="none"
          className={styles.sparklineLine}
          strokeWidth="1.75"
          strokeLinejoin="round"
          strokeLinecap="round"
        />
      )}
      {coords.map((c, i) => (
        <circle
          key={i}
          cx={c.x}
          cy={c.y}
          r={i === lastIndex ? 3 : 1.5}
          className={i === lastIndex ? `${styles.sparklineDot} ${flagClass(c.point.flag)}` : styles.sparklineDotMuted}
        />
      ))}
    </svg>
  );
}

function LabRow({ trend }: { trend: LabTrend }) {
  const latest = trend.points[trend.points.length - 1];
  if (!latest) return null;
  return (
    <li className={styles.labRow}>
      <div className={styles.labInfo}>
        <div className={styles.labAnalyteRow}>
          <span className={styles.labAnalyte}>{trend.analyte}</span>
          {latest.flag && (
            <span className={`${styles.flagTag} ${flagClass(latest.flag)}`}>{FLAG_LABEL[latest.flag]}</span>
          )}
        </div>
        <div className={styles.labValueRow}>
          <span className={`${styles.labValue} ${flagClass(latest.flag)}`}>
            {latest.value} <span className={styles.labUnit}>{trend.unit}</span>
          </span>
          <span className={styles.labDate}>as of {latest.date}</span>
        </div>
      </div>
      <Sparkline trend={trend} />
    </li>
  );
}

/**
 * Collapsible panel giving the clinician everything needed for manual
 * chart review — patient history and lab trends — independent of and
 * alongside whatever the AI pipeline found (or failed to find). Shown for
 * every patient, including FAILED/error runs, since that's exactly when
 * manual review matters most.
 */
export function ManualReviewPanel({
  timeline,
  labs,
}: {
  timeline: TimelineEvent[];
  labs: LabTrend[];
}) {
  const [open, setOpen] = useState(false);
  const baseId = useId();
  const triggerId = `${baseId}-trigger`;
  const contentId = `${baseId}-content`;

  return (
    <section className={styles.wrap} aria-labelledby={triggerId}>
      <h2 className={styles.headingWrap}>
        <button
          type="button"
          id={triggerId}
          className={styles.trigger}
          aria-expanded={open}
          aria-controls={contentId}
          onClick={() => setOpen((o) => !o)}
        >
          <span className={styles.triggerText}>
            <span className={styles.triggerLabel}>Manual review</span>
            <span className={styles.triggerHint}>Patient history &amp; lab trends, for clinician review</span>
          </span>
          <ShapeIcon shape="triangle" className={`${styles.chevron} ${open ? styles.chevronOpen : ""}`} />
        </button>
      </h2>

      <div id={contentId} className={styles.content} data-open={open} inert={!open}>
        <div className={styles.contentInner}>
          <div className={styles.section}>
            <h3 className={styles.sectionHeading}>Patient history</h3>
            <Timeline events={timeline} />
          </div>

          <div className={styles.section}>
            <h3 className={styles.sectionHeading}>Recent labs</h3>
            {labs.length === 0 ? (
              <p className={styles.empty}>No lab trends on file.</p>
            ) : (
              <ul className={styles.labList}>
                {labs.map((trend) => (
                  <LabRow key={trend.analyte} trend={trend} />
                ))}
              </ul>
            )}
          </div>
        </div>
      </div>
    </section>
  );
}
