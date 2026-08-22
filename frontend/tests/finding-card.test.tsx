import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { axe, type AxeResults } from "jest-axe";
import { FindingCard } from "@/components/FindingCard";
import { patients } from "@/lib/mockData";

function seriousOrCritical(results: AxeResults) {
  return results.violations.filter((v) => v.impact === "serious" || v.impact === "critical");
}

const flaggedPatient = patients.find((p) => p.status === "FLAGGED_FOR_REVIEW" && p.findings.length > 0);
if (!flaggedPatient) {
  throw new Error("Test fixture error: expected a FLAGGED_FOR_REVIEW patient with findings in mock data");
}
const finding = flaggedPatient.findings[0];

describe("ClinicianActionControl (via FindingCard)", () => {
  let fetchMock: ReturnType<typeof vi.fn>;

  beforeEach(() => {
    fetchMock = vi.fn();
    vi.stubGlobal("fetch", fetchMock);
  });

  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("renders CONFIRM/OVERRIDE/CORRECT buttons with accessible names", () => {
    render(
      <FindingCard finding={finding} patientId={flaggedPatient.patientId} onViewEvidence={() => {}} />
    );

    expect(screen.getByRole("button", { name: "Confirm" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Override" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Correct" })).toBeInTheDocument();
  });

  it("shows a labeled note input and save control once an action is chosen", async () => {
    const user = userEvent.setup();
    render(
      <FindingCard finding={finding} patientId={flaggedPatient.patientId} onViewEvidence={() => {}} />
    );

    expect(screen.queryByLabelText(/note \(optional\)/i)).not.toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "Confirm" }));

    expect(screen.getByLabelText(/note \(optional\)/i)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /save label/i })).toBeInTheDocument();
  });

  it("posts to /api/clinician-action with the expected payload and shows a saved state", async () => {
    fetchMock.mockResolvedValueOnce({ ok: true, json: async () => ({}) });
    const user = userEvent.setup();
    render(
      <FindingCard finding={finding} patientId={flaggedPatient.patientId} onViewEvidence={() => {}} />
    );

    await user.click(screen.getByRole("button", { name: "Override" }));
    await user.type(screen.getByLabelText(/note \(optional\)/i), "clinical context");
    await user.click(screen.getByRole("button", { name: /save label/i }));

    expect(fetchMock).toHaveBeenCalledWith(
      "/api/clinician-action",
      expect.objectContaining({
        method: "POST",
        body: JSON.stringify({
          patientId: flaggedPatient.patientId,
          claimId: finding.claimId,
          action: "OVERRIDE",
          note: "clinical context",
          verdictShown: finding.verdict,
          actionId: `${flaggedPatient.patientId}:${finding.claimId}`,
        }),
      })
    );
    expect(await screen.findByText("Saved.")).toBeInTheDocument();
  });

  it("shows an inline error state and never throws when the POST fails", async () => {
    fetchMock.mockResolvedValueOnce({ ok: false, json: async () => ({}) });
    const user = userEvent.setup();
    render(
      <FindingCard finding={finding} patientId={flaggedPatient.patientId} onViewEvidence={() => {}} />
    );

    await user.click(screen.getByRole("button", { name: "Correct" }));
    await user.click(screen.getByRole("button", { name: /save label/i }));

    expect(await screen.findByText(/couldn't save/i)).toBeInTheDocument();
  });

  it("shows an inline error state when fetch rejects (network failure)", async () => {
    fetchMock.mockRejectedValueOnce(new Error("network down"));
    const user = userEvent.setup();
    render(
      <FindingCard finding={finding} patientId={flaggedPatient.patientId} onViewEvidence={() => {}} />
    );

    await user.click(screen.getByRole("button", { name: "Confirm" }));
    await user.click(screen.getByRole("button", { name: /save label/i }));

    expect(await screen.findByText(/couldn't save/i)).toBeInTheDocument();
  });

  it("has zero serious/critical axe violations with the label control open", async () => {
    const user = userEvent.setup();
    const { container } = render(
      <FindingCard finding={finding} patientId={flaggedPatient.patientId} onViewEvidence={() => {}} />
    );

    await user.click(screen.getByRole("button", { name: "Confirm" }));

    const results = await axe(container);
    expect(seriousOrCritical(results)).toEqual([]);
  });
});
