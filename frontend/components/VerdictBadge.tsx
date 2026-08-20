import type { Verdict, CitationVerdict } from "@/lib/types";
import { Badge, type BadgeVariant } from "./Badge";
import type { IconShape } from "./icons";

const VERDICT_CONFIG: Record<Verdict, { variant: BadgeVariant; shape: IconShape; label: string }> = {
  VERIFIED: { variant: "verified", shape: "check-circle", label: "Verified" },
  PARTIALLY_VERIFIED: { variant: "moderate", shape: "help-circle", label: "Partially verified" },
  CONFLICTING: { variant: "high", shape: "triangle", label: "Conflicting" },
  UNVERIFIABLE: { variant: "info", shape: "help-circle", label: "Unverifiable" },
  REJECTED: { variant: "rejected", shape: "x-circle", label: "Rejected" },
  REQUIRES_REVIEW: { variant: "review", shape: "hex", label: "Requires review" },
};

export function VerdictBadge({ verdict }: { verdict: Verdict }) {
  const cfg = VERDICT_CONFIG[verdict];
  return <Badge variant={cfg.variant} shape={cfg.shape} label={cfg.label} />;
}

const CITATION_VERDICT_CONFIG: Record<
  CitationVerdict,
  { variant: BadgeVariant; shape: IconShape; label: string }
> = {
  VERIFIED_SPAN: { variant: "verified", shape: "check-circle", label: "Verified span" },
  REJECT: { variant: "rejected", shape: "x-circle", label: "Rejected" },
  FLAG_FOR_REVIEW: { variant: "review", shape: "hex", label: "Flag for review" },
};

export function CitationVerdictBadge({ verdict }: { verdict: CitationVerdict }) {
  const cfg = CITATION_VERDICT_CONFIG[verdict];
  return <Badge variant={cfg.variant} shape={cfg.shape} label={cfg.label} />;
}
