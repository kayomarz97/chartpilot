import type { RunStatus } from "@/lib/types";
import { Badge, type BadgeVariant } from "./Badge";
import type { IconShape } from "./icons";

const STATUS_CONFIG: Record<RunStatus, { variant: BadgeVariant; shape: IconShape; label: string }> = {
  QUEUED: { variant: "queued", shape: "clock", label: "Queued" },
  RUNNING: { variant: "info", shape: "clock", label: "Running" },
  COMPLETED: { variant: "verified", shape: "check-circle", label: "Completed" },
  PARTIAL: { variant: "moderate", shape: "square", label: "Partial" },
  FLAGGED_FOR_REVIEW: { variant: "review", shape: "hex", label: "Flagged for review" },
  FAILED: { variant: "failed", shape: "x-circle", label: "Processing error" },
  TIMED_OUT: { variant: "failed", shape: "clock", label: "Timed out" },
  DEAD_LETTER: { variant: "failed", shape: "octagon", label: "Dead letter" },
};

export function StatusBadge({ status }: { status: RunStatus }) {
  const cfg = STATUS_CONFIG[status];
  return <Badge variant={cfg.variant} shape={cfg.shape} label={cfg.label} />;
}
