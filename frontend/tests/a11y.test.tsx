import { describe, it, expect, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { axe, type AxeResults } from "jest-axe";
import DashboardPage from "@/app/page";
import { PatientView } from "@/components/PatientView";
import { patients } from "@/lib/mockData";

// next/link pulls in app-router context that isn't present in a bare RTL
// render; swap it for a plain anchor so these tests exercise our own
// markup/a11y wiring rather than Next's router internals.
vi.mock("next/link", () => ({
  default: ({
    href,
    children,
    ...props
  }: React.AnchorHTMLAttributes<HTMLAnchorElement> & { href: string; children: React.ReactNode }) => (
    <a href={href} {...props}>
      {children}
    </a>
  ),
}));

function seriousOrCritical(results: AxeResults) {
  return results.violations.filter((v) => v.impact === "serious" || v.impact === "critical");
}

const flaggedPatient = patients.find((p) => p.status === "FLAGGED_FOR_REVIEW" && p.findings.length > 0);
if (!flaggedPatient) {
  throw new Error("Test fixture error: expected a FLAGGED_FOR_REVIEW patient with findings in mock data");
}

describe("accessibility (axe)", () => {
  it("dashboard has zero serious/critical violations", async () => {
    const { container } = render(<DashboardPage />);
    const results = await axe(container);
    expect(seriousOrCritical(results)).toEqual([]);
  });

  it("flagged patient view has zero serious/critical violations", async () => {
    const { container } = render(<PatientView patient={flaggedPatient} />);
    const results = await axe(container);
    expect(seriousOrCritical(results)).toEqual([]);
  });

  it("open evidence drawer has zero serious/critical violations", async () => {
    const user = userEvent.setup();
    const { container } = render(<PatientView patient={flaggedPatient} />);

    const openButton = screen.getByRole("button", { name: /view evidence/i });
    await user.click(openButton);

    // The dialog should be open and focus-managed before we scan it.
    const dialog = screen.getByRole("dialog", { name: /evidence for this finding/i });
    expect(dialog).toBeInTheDocument();

    const results = await axe(container);
    expect(seriousOrCritical(results)).toEqual([]);
  });
});
