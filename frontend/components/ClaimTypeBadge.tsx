import type { ClaimType } from "@/lib/types";
import { Badge, type BadgeVariant } from "./Badge";
import type { IconShape } from "./icons";

const CLAIM_TYPE_CONFIG: Record<ClaimType, { variant: BadgeVariant; shape: IconShape; label: string }> = {
  PATIENT_FACT: { variant: "info", shape: "circle", label: "Patient fact" },
  REGULATORY_FACT: { variant: "low", shape: "square", label: "Regulatory fact" },
  GUIDELINE_RECOMMENDATION: { variant: "verified", shape: "diamond", label: "Guideline recommendation" },
  PATIENT_SPECIFIC_INFERENCE: { variant: "queued", shape: "help-circle", label: "Patient-specific inference" },
  POSSIBLE_CONCERN: { variant: "high", shape: "triangle", label: "Possible concern" },
  CLINICIAN_REVIEW_SUGGESTION: { variant: "review", shape: "hex", label: "Clinician review suggestion" },
  UNCERTAINTY: { variant: "moderate", shape: "help-circle", label: "Uncertainty" },
};

export function ClaimTypeBadge({ claimType }: { claimType: ClaimType }) {
  const cfg = CLAIM_TYPE_CONFIG[claimType];
  return <Badge variant={cfg.variant} shape={cfg.shape} label={cfg.label} />;
}
