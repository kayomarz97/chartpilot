"use client";

import { useEffect, useRef } from "react";
import type { Finding } from "@/lib/types";
import { CitationVerdictBadge } from "./VerdictBadge";
import { Badge } from "./Badge";
import { ShapeIcon } from "./icons";
import styles from "./EvidenceDrawer.module.css";

const TIER_LABEL: Record<string, string> = {
  REGULATORY_LABEL: "Regulatory label",
  LITERATURE: "Literature",
  GUIDELINE: "Guideline",
};

/**
 * The evidence showpiece: a focus-managed dialog listing, for the selected
 * finding, every external evidence item with its full provenance —
 * publisher, jurisdiction, snapshot, verbatim span, computed offsets,
 * citation-gate results, the Model B cross-check, and clinician-review
 * status (spec §58).
 */
export function EvidenceDrawer({
  finding,
  onClose,
}: {
  finding: Finding | null;
  onClose: () => void;
}) {
  const isOpen = finding !== null;
  const drawerRef = useRef<HTMLDivElement>(null);
  const closeButtonRef = useRef<HTMLButtonElement>(null);
  const previouslyFocused = useRef<HTMLElement | null>(null);

  useEffect(() => {
    if (isOpen) {
      previouslyFocused.current = document.activeElement as HTMLElement | null;
      closeButtonRef.current?.focus();

      const handleKeyDown = (e: KeyboardEvent) => {
        if (e.key === "Escape") {
          e.preventDefault();
          onClose();
          return;
        }
        if (e.key === "Tab") {
          const focusables = drawerRef.current?.querySelectorAll<HTMLElement>(
            'a[href], button:not([disabled]), [tabindex]:not([tabindex="-1"])'
          );
          if (!focusables || focusables.length === 0) return;
          const list = Array.from(focusables);
          const first = list[0]!;
          const last = list[list.length - 1]!;
          if (e.shiftKey && document.activeElement === first) {
            e.preventDefault();
            last.focus();
          } else if (!e.shiftKey && document.activeElement === last) {
            e.preventDefault();
            first.focus();
          }
        }
      };

      document.addEventListener("keydown", handleKeyDown);
      return () => document.removeEventListener("keydown", handleKeyDown);
    }

    previouslyFocused.current?.focus();
    return undefined;
  }, [isOpen, onClose]);

  return (
    <>
      <div
        className={styles.overlay}
        data-open={isOpen}
        aria-hidden="true"
        onClick={isOpen ? onClose : undefined}
      />
      <div
        ref={drawerRef}
        className={styles.drawer}
        data-open={isOpen}
        role="dialog"
        aria-modal="true"
        aria-labelledby="evidence-drawer-title"
        inert={!isOpen}
      >
        <div className={styles.header}>
          <div>
            <h2 id="evidence-drawer-title" className={styles.headerTitle}>
              Evidence for this finding
            </h2>
            {finding && <p className={styles.headerClaim}>{finding.statement}</p>}
          </div>
          <button
            ref={closeButtonRef}
            type="button"
            className={styles.closeButton}
            onClick={onClose}
            aria-label="Close evidence drawer"
          >
            <ShapeIcon shape="x-circle" />
          </button>
        </div>

        <div className={styles.body}>
          <div aria-live="polite" className="visually-hidden">
            {isOpen && finding
              ? `Evidence drawer open, showing ${finding.externalEvidence.length} source${
                  finding.externalEvidence.length === 1 ? "" : "s"
                }.`
              : ""}
          </div>

          {finding?.externalEvidence.map((ev) => {
            const reviewed = ev.reviewedBy !== null && ev.reviewedBy !== "PENDING";
            return (
              <section key={ev.evidenceId} className={styles.evidenceCard} aria-label={`${ev.publisher} evidence`}>
                <div className={styles.evidenceHead}>
                  <span className={styles.publisher}>{ev.publisher}</span>
                  <span className={styles.jurisdiction}>{ev.jurisdiction}</span>
                  <Badge variant="info" shape="square" label={TIER_LABEL[ev.tier] ?? ev.tier} />
                </div>

                <div className={styles.metaGrid}>
                  <div className={styles.metaItem}>
                    <div className={styles.metaLabel}>Publication date</div>
                    <div className={styles.metaValue}>{ev.publicationDate}</div>
                  </div>
                  <div className={styles.metaItem}>
                    <div className={styles.metaLabel}>Version</div>
                    <div className={styles.metaValue}>{ev.version}</div>
                  </div>
                  <div className={styles.metaItem}>
                    <div className={styles.metaLabel}>Snapshot ID</div>
                    <div className={styles.metaValue}>{ev.snapshotId}</div>
                  </div>
                  <div className={styles.metaItem}>
                    <div className={styles.metaLabel}>Source URL</div>
                    <div className={styles.metaValue}>
                      <a href={ev.sourceUrl} target="_blank" rel="noreferrer noopener">
                        {ev.sourceUrl}
                      </a>
                    </div>
                  </div>
                </div>

                <div>
                  <div className={styles.sectionLabel}>Verbatim supporting span</div>
                  <blockquote className={styles.verbatim}>&ldquo;{ev.verbatimSpan}&rdquo;</blockquote>
                  <div className={styles.offsets}>
                    Computed source location: characters {ev.computedStartOffset}–{ev.computedEndOffset}
                  </div>
                </div>

                <div>
                  <div className={styles.sectionLabel}>Citation verification</div>
                  <div className={styles.gateRow}>
                    <CitationVerdictBadge verdict={ev.citationVerdict} />
                    {ev.gatesPassed.map((g) => (
                      <Badge
                        key={g.gate}
                        variant={g.passed ? "verified" : "rejected"}
                        shape={g.passed ? "check-circle" : "x-circle"}
                        label={g.gate}
                      />
                    ))}
                  </div>
                </div>

                <div>
                  <div className={styles.sectionLabel}>Model B cross-check</div>
                  <p className={styles.modelB}>
                    {ev.modelBFinding}{" "}
                    <strong>{ev.modelBShouldReject ? "Recommends rejection." : "Does not recommend rejection."}</strong>
                  </p>
                </div>

                <div
                  className={`${styles.reviewNote} ${reviewed ? styles.reviewNoteDone : styles.reviewNotePending}`}
                >
                  <ShapeIcon shape={reviewed ? "check-circle" : "help-circle"} />
                  {reviewed
                    ? `Source clinician-reviewed (${ev.reviewedBy}).`
                    : "Source not yet clinician-reviewed."}
                </div>
              </section>
            );
          })}
        </div>
      </div>
    </>
  );
}
