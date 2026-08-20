import type { PatientRun } from "./types";

// Synthetic demo data only — no real patient information. Doubles as the
// typed mock layer the UI is built against until the backend API exists,
// and as the precomputed dataset used for live demos.

const aaravSharma: PatientRun = {
  runId: "run-8f21-aarav",
  patientId: "MRN-48213",
  patientName: "Aarav Sharma",
  status: "FLAGGED_FOR_REVIEW",
  stage: "CLINICIAN_REVIEW",
  findings: [
    {
      claimId: "claim-aarav-hyperkalemia",
      claimType: "POSSIBLE_CONCERN",
      statement:
        "Recent potassium of 6.2 mmol/L identified in a patient on lisinopril 20 mg daily suggests possible ACE-inhibitor-associated hyperkalemia and may warrant review before this visit.",
      severity: "CRITICAL",
      verdict: "REQUIRES_REVIEW",
      rationale:
        "Serum potassium has risen from 4.4 to 6.2 mmol/L over three draws following initiation of lisinopril in a patient with pre-existing stage 3 chronic kidney disease. The FDA label for ACE inhibitors identifies hyperkalemia as a labeled risk, particularly with renal impairment. No subsequent evidence identified that this trend has been addressed in the chart.",
      recommendedAction:
        "Consider repeat basic metabolic panel prior to prescribing, and clinician review of lisinopril dosing in the context of renal function and potassium trend.",
      patientEvidence: [
        {
          label: "Potassium (BMP)",
          detail: "6.2 mmol/L on 2026-08-14 (reference range 3.5–5.0 mmol/L)",
        },
        {
          label: "Potassium (BMP)",
          detail: "5.1 mmol/L on 2026-07-30 (reference range 3.5–5.0 mmol/L)",
        },
        {
          label: "Active medication",
          detail: "Lisinopril 20 mg PO daily, started 2026-07-02",
        },
        {
          label: "Active diagnosis",
          detail: "Chronic kidney disease, stage 3 (eGFR 52 mL/min/1.73m²)",
        },
      ],
      externalEvidence: [
        {
          evidenceId: "ev-fda-lisinopril-label",
          tier: "REGULATORY_LABEL",
          publisher: "U.S. Food & Drug Administration",
          jurisdiction: "US FDA LABEL",
          publicationDate: "2024-03-11",
          version: "Rev. 14",
          sourceUrl: "https://www.accessdata.fda.gov/drugsatfda_docs/label/2024/019777s098lbl.pdf",
          snapshotId: "snap-fda-lisinopril-2024-03-11-14",
          verbatimSpan:
            "Hyperkalemia: Elevated serum potassium has been observed in some patients treated with lisinopril. Risk factors for the development of hyperkalemia include renal insufficiency, diabetes mellitus, and concomitant use of potassium-sparing diuretics, potassium supplements, or potassium-containing salt substitutes.",
          computedStartOffset: 4218,
          computedEndOffset: 4512,
          citationVerdict: "VERIFIED_SPAN",
          gatesPassed: [
            { gate: "Source retrievable", passed: true },
            { gate: "Snapshot hash matches", passed: true },
            { gate: "Span located verbatim", passed: true },
            { gate: "Offsets resolve to span", passed: true },
            { gate: "Publisher allow-listed", passed: true },
          ],
          modelBFinding:
            "The cited span directly supports the claim that lisinopril carries a labeled hyperkalemia risk, elevated by renal insufficiency.",
          modelBShouldReject: false,
          reviewedBy: "clin_rn_8842",
        },
        {
          evidenceId: "ev-pubmed-acei-hyperkalemia",
          tier: "LITERATURE",
          publisher: "PubMed (National Library of Medicine)",
          jurisdiction: "United States",
          publicationDate: "2021-09-02",
          version: "PMID 34489521",
          sourceUrl: "https://pubmed.ncbi.nlm.nih.gov/34489521/",
          snapshotId: "snap-pubmed-34489521-2021-09-02",
          verbatimSpan:
            "Among patients with stage 3-4 CKD initiating ACE inhibitor therapy, hyperkalemia (K+ > 5.5 mmol/L) occurred in 17.4% within the first 90 days, with risk increasing alongside baseline eGFR reduction.",
          computedStartOffset: 812,
          computedEndOffset: 1024,
          citationVerdict: "FLAG_FOR_REVIEW",
          gatesPassed: [
            { gate: "Source retrievable", passed: true },
            { gate: "Snapshot hash matches", passed: true },
            { gate: "Span located verbatim", passed: true },
            { gate: "Offsets resolve to span", passed: false },
            { gate: "Publisher allow-listed", passed: true },
          ],
          modelBFinding:
            "The span supports an association between ACE-inhibitor initiation and hyperkalemia in CKD populations, but computed offsets do not cleanly resolve to the quoted sentence boundaries.",
          modelBShouldReject: false,
          reviewedBy: null,
        },
      ],
    },
  ],
  timeline: [
    {
      date: "2026-05-18",
      kind: "DIAGNOSIS",
      label: "Chronic kidney disease, stage 3 diagnosed",
      detail: "eGFR 54 mL/min/1.73m², confirmed on repeat testing.",
    },
    {
      date: "2026-07-02",
      kind: "MEDICATION",
      label: "Lisinopril 20 mg daily started",
      detail: "Initiated for blood pressure management.",
    },
    {
      date: "2026-07-30",
      kind: "LAB",
      label: "Potassium 5.1 mmol/L",
      detail: "Basic metabolic panel, mildly elevated above reference range.",
      severity: "MODERATE",
    },
    {
      date: "2026-08-14",
      kind: "LAB",
      label: "Potassium 6.2 mmol/L",
      detail: "Basic metabolic panel, markedly elevated above reference range.",
      severity: "CRITICAL",
    },
    {
      date: "2026-08-18",
      kind: "ENCOUNTER",
      label: "Chart prepared for upcoming visit",
      detail: "Pre-visit chart review generated ahead of scheduled follow-up.",
    },
  ],
};

const priyaNair: PatientRun = {
  runId: "run-3c74-priya",
  patientId: "MRN-51907",
  patientName: "Priya Nair",
  status: "COMPLETED",
  stage: "DONE",
  findings: [],
  timeline: [
    {
      date: "2026-02-04",
      kind: "ENCOUNTER",
      label: "Annual wellness visit",
      detail: "Routine annual exam, no acute concerns raised.",
    },
    {
      date: "2026-02-04",
      kind: "LAB",
      label: "Lipid panel within reference range",
      detail: "LDL 96 mg/dL, HDL 58 mg/dL, triglycerides 110 mg/dL.",
    },
    {
      date: "2026-05-11",
      kind: "MEDICATION",
      label: "Levothyroxine 50 mcg daily continued",
      detail: "Refill of stable, long-standing thyroid replacement dose.",
    },
    {
      date: "2026-08-09",
      kind: "LAB",
      label: "TSH within reference range",
      detail: "TSH 2.1 mIU/L, consistent with adequate thyroid replacement.",
    },
  ],
};

const rahulVerma: PatientRun = {
  runId: "run-9a02-rahul",
  patientId: "MRN-60335",
  patientName: "Rahul Verma",
  status: "FLAGGED_FOR_REVIEW",
  stage: "CLINICIAN_REVIEW",
  findings: [
    {
      claimId: "claim-rahul-statin-myalgia",
      claimType: "PATIENT_SPECIFIC_INFERENCE",
      statement:
        "Reported new muscle aches since starting atorvastatin 40 mg may be statin-associated and could warrant review of the current dose.",
      severity: "MODERATE",
      verdict: "PARTIALLY_VERIFIED",
      rationale:
        "The temporal association between statin initiation and the onset of myalgia is consistent with statin-associated muscle symptoms described in clinical guidelines, but no creatine kinase level is on file to corroborate the association, and the supporting guideline source has not yet been clinician-reviewed.",
      recommendedAction:
        "Consider checking creatine kinase and reviewing statin dose or alternative therapy if symptoms persist.",
      patientEvidence: [
        {
          label: "Patient-reported symptom",
          detail: "New bilateral thigh muscle aches, onset 2026-07-20, reported at telehealth check-in",
        },
        {
          label: "Active medication",
          detail: "Atorvastatin 40 mg PO nightly, started 2026-06-15",
        },
      ],
      externalEvidence: [
        {
          evidenceId: "ev-guideline-statin-myalgia",
          tier: "GUIDELINE",
          publisher: "American College of Cardiology / American Heart Association",
          jurisdiction: "United States",
          publicationDate: "2023-11-01",
          version: "2023 Statin Safety Guidance, v2",
          sourceUrl: "https://www.acc.org/guidelines/statin-associated-muscle-symptoms",
          snapshotId: "snap-acc-aha-statin-2023-11-01-v2",
          verbatimSpan:
            "Statin-associated muscle symptoms (SAMS) typically emerge within the first months of therapy or after a dose increase, and evaluation should include creatine kinase measurement to distinguish SAMS from other causes of myalgia.",
          computedStartOffset: 2140,
          computedEndOffset: 2378,
          citationVerdict: "VERIFIED_SPAN",
          gatesPassed: [
            { gate: "Source retrievable", passed: true },
            { gate: "Snapshot hash matches", passed: true },
            { gate: "Span located verbatim", passed: true },
            { gate: "Offsets resolve to span", passed: true },
            { gate: "Publisher allow-listed", passed: true },
          ],
          modelBFinding:
            "The span supports the general association between statin initiation and muscle symptoms and recommends creatine kinase testing, consistent with the claim.",
          modelBShouldReject: false,
          reviewedBy: "PENDING",
        },
      ],
    },
  ],
  timeline: [
    {
      date: "2026-06-15",
      kind: "MEDICATION",
      label: "Atorvastatin 40 mg nightly started",
      detail: "Initiated for hyperlipidemia management.",
    },
    {
      date: "2026-07-20",
      kind: "ENCOUNTER",
      label: "Telehealth check-in",
      detail: "Patient reported new bilateral thigh muscle aches.",
      severity: "MODERATE",
    },
    {
      date: "2026-08-16",
      kind: "ENCOUNTER",
      label: "Chart prepared for upcoming visit",
      detail: "Pre-visit chart review generated ahead of scheduled follow-up.",
    },
  ],
};

const meeraIyer: PatientRun = {
  runId: "run-5e19-meera",
  patientId: "MRN-77241",
  patientName: "Meera Iyer",
  status: "FAILED",
  stage: "EVIDENCE_RETRIEVAL",
  findings: [],
  timeline: [
    {
      date: "2026-08-17",
      kind: "ENCOUNTER",
      label: "Chart prep run started",
      detail: "Automated pre-visit chart preparation queued.",
    },
  ],
};

const sanjayRao: PatientRun = {
  runId: "run-c440-sanjay",
  patientId: "MRN-83562",
  patientName: "Sanjay Rao",
  status: "DEAD_LETTER",
  stage: "CITATION_VERIFICATION",
  findings: [],
  timeline: [
    {
      date: "2026-08-12",
      kind: "ENCOUNTER",
      label: "Chart prep run started",
      detail: "Automated pre-visit chart preparation queued.",
    },
  ],
};

export const patients: PatientRun[] = [
  aaravSharma,
  priyaNair,
  rahulVerma,
  meeraIyer,
  sanjayRao,
];

export function getPatientById(patientId: string): PatientRun | undefined {
  return patients.find((p) => p.patientId === patientId);
}
