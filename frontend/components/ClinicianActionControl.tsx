"use client";

import { useId, useState } from "react";
import type { ClinicianActionKind } from "@/lib/types";
import styles from "./ClinicianActionControl.module.css";

const ACTIONS: { kind: ClinicianActionKind; label: string }[] = [
  { kind: "CONFIRM", label: "Confirm" },
  { kind: "OVERRIDE", label: "Override" },
  { kind: "CORRECT", label: "Correct" },
];

type SaveStatus = "idle" | "saving" | "saved" | "error";

/**
 * Per-finding clinician label control (Phase B, spec §53): CONFIRM /
 * OVERRIDE / CORRECT, plus an optional note. This is the ground-truth
 * signal the outer self-improving loop (Phase C) trains toward, so a
 * submission is persisted via the same-origin `/api/clinician-action`
 * proxy (never a direct call to the private backend).
 *
 * `note` is free text a clinician may type to explain an override/
 * correction — the backend stores it as `trusted=False` (spec §53): it is
 * a label for a human/the outer loop to read, never a fact/rule/gate input.
 *
 * Graceful by construction: a failed POST shows an inline "couldn't save"
 * message and lets the clinician retry — it never throws.
 */
export function ClinicianActionControl({
  patientId,
  claimId,
  verdictShown,
}: {
  patientId: string;
  claimId: string;
  verdictShown: string | null;
}) {
  const [selected, setSelected] = useState<ClinicianActionKind | null>(null);
  const [note, setNote] = useState("");
  const [status, setStatus] = useState<SaveStatus>("idle");
  const baseId = useId();
  const noteId = `${baseId}-note`;
  const statusId = `${baseId}-status`;

  const actionId = `${patientId}:${claimId}`;

  function selectAction(kind: ClinicianActionKind) {
    setSelected(kind);
    setStatus("idle");
  }

  async function handleSave() {
    if (!selected) return;
    setStatus("saving");
    try {
      const response = await fetch("/api/clinician-action", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          patientId,
          claimId,
          action: selected,
          note,
          verdictShown,
          actionId,
        }),
      });
      setStatus(response.ok ? "saved" : "error");
    } catch {
      setStatus("error");
    }
  }

  return (
    <div className={styles.wrap}>
      <div className={styles.sectionLabel} id={`${baseId}-label`}>
        Clinician label
      </div>
      <div className={styles.buttonRow} role="group" aria-labelledby={`${baseId}-label`}>
        {ACTIONS.map(({ kind, label }) => (
          <button
            key={kind}
            type="button"
            className={styles.actionButton}
            aria-pressed={selected === kind}
            data-selected={selected === kind}
            onClick={() => selectAction(kind)}
          >
            {label}
          </button>
        ))}
      </div>

      {selected && (
        <div className={styles.noteArea}>
          <label htmlFor={noteId} className={styles.noteLabel}>
            Note (optional)
          </label>
          <textarea
            id={noteId}
            className={styles.noteInput}
            value={note}
            onChange={(e) => setNote(e.target.value)}
            rows={2}
            placeholder="Add context for this label…"
          />
          <div className={styles.saveRow}>
            <button
              type="button"
              className={styles.saveButton}
              onClick={handleSave}
              disabled={status === "saving"}
            >
              {status === "saving" ? "Saving…" : "Save label"}
            </button>
            <span id={statusId} role="status" className={styles.statusText}>
              {status === "saved" && "Saved."}
              {status === "error" && "Couldn't save — please try again."}
            </span>
          </div>
        </div>
      )}
    </div>
  );
}
