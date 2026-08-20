import type { Severity } from "@/lib/types";
import { Badge, type BadgeVariant } from "./Badge";
import type { IconShape } from "./icons";

const SEVERITY_CONFIG: Record<
  Exclude<Severity, null>,
  { variant: BadgeVariant; shape: IconShape; label: string }
> = {
  CRITICAL: { variant: "critical", shape: "triangle", label: "Critical" },
  HIGH: { variant: "high", shape: "triangle", label: "High" },
  MODERATE: { variant: "moderate", shape: "square", label: "Moderate" },
  LOW: { variant: "low", shape: "diamond", label: "Low" },
  INFO: { variant: "info", shape: "circle", label: "Info" },
};

export function SeverityBadge({ severity }: { severity: Severity }) {
  if (severity === null) {
    return <Badge variant="queued" shape="circle" label="Ungraded" />;
  }
  const cfg = SEVERITY_CONFIG[severity];
  return <Badge variant={cfg.variant} shape={cfg.shape} label={cfg.label} />;
}
