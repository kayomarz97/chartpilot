"use client";

import { useState } from "react";
import type { TimelineEvent, TimelineEventKind } from "@/lib/types";
import { ShapeIcon, type IconShape } from "./icons";
import styles from "./Timeline.module.css";

const KIND_ICON: Record<TimelineEventKind, IconShape> = {
  LAB: "square",
  MEDICATION: "diamond",
  DIAGNOSIS: "triangle",
  ENCOUNTER: "circle",
  ADVERSE_EVENT: "octagon",
  PROCEDURE: "hex",
};

const FILTER_CHIPS: { kind: TimelineEventKind; label: string }[] = [
  { kind: "LAB", label: "Labs" },
  { kind: "MEDICATION", label: "Medications" },
  { kind: "DIAGNOSIS", label: "Diagnoses" },
  { kind: "ADVERSE_EVENT", label: "Safety signals" },
];

const FILTERABLE_KINDS = new Set(FILTER_CHIPS.map((c) => c.kind));

export function Timeline({ events }: { events: TimelineEvent[] }) {
  const [activeKinds, setActiveKinds] = useState<Set<TimelineEventKind>>(
    () => new Set(FILTER_CHIPS.map((c) => c.kind))
  );

  function toggle(kind: TimelineEventKind) {
    setActiveKinds((prev) => {
      const next = new Set(prev);
      if (next.has(kind)) {
        next.delete(kind);
      } else {
        next.add(kind);
      }
      return next;
    });
  }

  const visibleEvents = events.filter(
    (e) => !FILTERABLE_KINDS.has(e.kind) || activeKinds.has(e.kind)
  );
  const sorted = [...visibleEvents].sort((a, b) => a.date.localeCompare(b.date));

  return (
    <div className={styles.wrap}>
      <div className={styles.filters} role="group" aria-label="Filter timeline by event type">
        {FILTER_CHIPS.map((chip) => {
          const active = activeKinds.has(chip.kind);
          return (
            <button
              key={chip.kind}
              type="button"
              className={styles.chip}
              aria-pressed={active}
              onClick={() => toggle(chip.kind)}
            >
              <ShapeIcon shape={KIND_ICON[chip.kind]} />
              {chip.label}
            </button>
          );
        })}
      </div>

      <div aria-live="polite" className="visually-hidden">
        {`Showing ${sorted.length} of ${events.length} timeline events.`}
      </div>

      {sorted.length === 0 ? (
        <p className={styles.empty}>No timeline events match the selected filters.</p>
      ) : (
        <ol className={styles.list}>
          {sorted.map((event, i) => (
            <li key={i} className={styles.item}>
              <span className={styles.dot}>
                <ShapeIcon shape={KIND_ICON[event.kind]} />
              </span>
              <div className={styles.itemDate}>{event.date}</div>
              <div className={styles.itemLabel}>{event.label}</div>
              <div className={styles.itemDetail}>{event.detail}</div>
            </li>
          ))}
        </ol>
      )}
    </div>
  );
}
