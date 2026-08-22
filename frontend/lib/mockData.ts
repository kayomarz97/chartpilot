import type { PatientRun } from "./types";

// Synthetic demo data only — no real patient information. Doubles as the
// typed mock layer the UI is built against until the backend API exists,
// and as the fallback dataset rendered whenever the live backend
// (NEXT_PUBLIC_BACKEND_URL, see lib/liveData.ts) is unset or unreachable.
//
// Every patient carries a multi-year synthetic history (timeline + labs) so
// the manual-review panel has real trends to show a clinician, independent
// of whatever the AI pipeline did or didn't manage to process.

const aaravSharma: PatientRun = {
  runId: "run-8f21-aarav",
  patientId: "MRN-48213",
  patientName: "Aarav Sharma",
  status: "FLAGGED_FOR_REVIEW",
  stage: "CLINICIAN_REVIEW",
  findings: [
    {
      claimId: "claim-aarav-hyperkalemia",
      revisionAttempts: 0,
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
      date: "2024-01-15",
      kind: "ENCOUNTER",
      label: "Annual wellness visit",
      detail: "Routine physical; blood pressure mildly elevated at 138/86 mmHg. Renal function first noted as borderline.",
    },
    {
      date: "2024-01-15",
      kind: "LAB",
      label: "eGFR 68 mL/min/1.73m²",
      detail: "Basic metabolic panel; mildly reduced but not yet diagnostic of chronic kidney disease.",
    },
    {
      date: "2024-06-20",
      kind: "DIAGNOSIS",
      label: "Hypertension diagnosed",
      detail: "Stage 1 hypertension; lifestyle modification recommended before pharmacologic therapy.",
    },
    {
      date: "2024-11-05",
      kind: "LAB",
      label: "Potassium 4.2 mmol/L",
      detail: "Basic metabolic panel, within reference range (3.5–5.0 mmol/L).",
    },
    {
      date: "2024-11-05",
      kind: "LAB",
      label: "eGFR 61 mL/min/1.73m²",
      detail: "Basic metabolic panel; continued gradual decline in renal function.",
    },
    {
      date: "2025-03-12",
      kind: "ENCOUNTER",
      label: "Follow-up visit",
      detail: "Blood pressure remains elevated at 142/88 mmHg despite lifestyle changes; pharmacologic therapy discussed.",
    },
    {
      date: "2025-09-18",
      kind: "LAB",
      label: "eGFR 58 mL/min/1.73m²",
      detail: "Basic metabolic panel; further decline consistent with early chronic kidney disease.",
    },
    {
      date: "2025-09-18",
      kind: "LAB",
      label: "Potassium 4.4 mmol/L",
      detail: "Basic metabolic panel, within reference range (3.5–5.0 mmol/L).",
    },
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
      date: "2026-07-30",
      kind: "LAB",
      label: "eGFR 51 mL/min/1.73m²",
      detail: "Basic metabolic panel; modest further decline after ACE-inhibitor initiation.",
      severity: "LOW",
    },
    {
      date: "2026-08-14",
      kind: "LAB",
      label: "Potassium 6.2 mmol/L",
      detail: "Basic metabolic panel, markedly elevated above reference range.",
      severity: "CRITICAL",
    },
    {
      date: "2026-08-14",
      kind: "LAB",
      label: "eGFR 47 mL/min/1.73m²",
      detail: "Basic metabolic panel; renal function has declined further, compounding hyperkalemia risk.",
      severity: "HIGH",
    },
    {
      date: "2026-08-18",
      kind: "ENCOUNTER",
      label: "Chart prepared for upcoming visit",
      detail: "Pre-visit chart review generated ahead of scheduled follow-up.",
    },
  ],
  labs: [
    {
      analyte: "Potassium",
      unit: "mmol/L",
      points: [
        { date: "2024-11-05", value: 4.2 },
        { date: "2025-09-18", value: 4.4 },
        { date: "2026-07-30", value: 5.1, flag: "HIGH" },
        { date: "2026-08-14", value: 6.2, flag: "CRITICAL" },
      ],
    },
    {
      analyte: "eGFR",
      unit: "mL/min/1.73m²",
      points: [
        { date: "2024-01-15", value: 68 },
        { date: "2024-11-05", value: 61 },
        { date: "2025-09-18", value: 58 },
        { date: "2026-05-18", value: 54, flag: "LOW" },
        { date: "2026-07-30", value: 51, flag: "LOW" },
        { date: "2026-08-14", value: 47, flag: "LOW" },
      ],
    },
    {
      analyte: "Creatinine",
      unit: "mg/dL",
      points: [
        { date: "2024-01-15", value: 1.0 },
        { date: "2024-11-05", value: 1.1 },
        { date: "2025-09-18", value: 1.3 },
        { date: "2026-05-18", value: 1.4, flag: "HIGH" },
        { date: "2026-08-14", value: 1.6, flag: "HIGH" },
      ],
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
      date: "2024-02-01",
      kind: "ENCOUNTER",
      label: "Annual wellness visit",
      detail: "Routine annual exam, no acute concerns raised.",
    },
    {
      date: "2024-02-01",
      kind: "LAB",
      label: "Lipid panel within reference range",
      detail: "LDL 101 mg/dL, HDL 55 mg/dL, triglycerides 118 mg/dL.",
    },
    {
      date: "2024-05-14",
      kind: "MEDICATION",
      label: "Levothyroxine 50 mcg daily continued",
      detail: "Refill of stable, long-standing thyroid replacement dose.",
    },
    {
      date: "2024-08-06",
      kind: "LAB",
      label: "TSH within reference range",
      detail: "TSH 2.3 mIU/L, consistent with adequate thyroid replacement.",
    },
    {
      date: "2025-02-03",
      kind: "ENCOUNTER",
      label: "Annual wellness visit",
      detail: "Routine annual exam, no acute concerns raised.",
    },
    {
      date: "2025-02-03",
      kind: "LAB",
      label: "Lipid panel within reference range",
      detail: "LDL 99 mg/dL, HDL 57 mg/dL, triglycerides 112 mg/dL.",
    },
    {
      date: "2025-05-12",
      kind: "MEDICATION",
      label: "Levothyroxine 50 mcg daily continued",
      detail: "Refill of stable, long-standing thyroid replacement dose.",
    },
    {
      date: "2025-08-08",
      kind: "LAB",
      label: "TSH within reference range",
      detail: "TSH 2.2 mIU/L, consistent with adequate thyroid replacement.",
    },
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
  labs: [
    {
      analyte: "TSH",
      unit: "mIU/L",
      points: [
        { date: "2024-08-06", value: 2.3 },
        { date: "2025-02-03", value: 2.0 },
        { date: "2025-08-08", value: 2.2 },
        { date: "2026-02-04", value: 2.4 },
        { date: "2026-08-09", value: 2.1 },
      ],
    },
    {
      analyte: "LDL Cholesterol",
      unit: "mg/dL",
      points: [
        { date: "2024-02-01", value: 101 },
        { date: "2025-02-03", value: 99 },
        { date: "2026-02-04", value: 96 },
      ],
    },
    {
      analyte: "Hemoglobin A1c",
      unit: "%",
      points: [
        { date: "2024-02-01", value: 5.3 },
        { date: "2025-02-03", value: 5.2 },
        { date: "2026-02-04", value: 5.3 },
      ],
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
      revisionAttempts: 0,
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
      date: "2024-01-15",
      kind: "LAB",
      label: "LDL cholesterol 175 mg/dL",
      detail: "Lipid panel; elevated LDL noted at annual exam.",
      severity: "MODERATE",
    },
    {
      date: "2024-01-15",
      kind: "DIAGNOSIS",
      label: "Hyperlipidemia diagnosed",
      detail: "Diet and exercise counseling recommended as first-line management.",
    },
    {
      date: "2024-07-20",
      kind: "LAB",
      label: "LDL cholesterol 168 mg/dL",
      detail: "Lipid panel; minimal improvement despite lifestyle changes.",
      severity: "MODERATE",
    },
    {
      date: "2025-01-10",
      kind: "LAB",
      label: "LDL cholesterol 171 mg/dL",
      detail: "Lipid panel; LDL remains above goal.",
      severity: "MODERATE",
    },
    {
      date: "2025-01-10",
      kind: "LAB",
      label: "Creatine kinase 88 U/L",
      detail: "Baseline creatine kinase, within reference range (30–200 U/L).",
    },
    {
      date: "2025-07-14",
      kind: "LAB",
      label: "LDL cholesterol 165 mg/dL",
      detail: "Lipid panel; LDL remains above goal despite continued lifestyle counseling.",
      severity: "MODERATE",
    },
    {
      date: "2026-06-01",
      kind: "ENCOUNTER",
      label: "Follow-up visit",
      detail: "LDL remains persistently elevated; statin therapy discussed and recommended.",
    },
    {
      date: "2026-06-01",
      kind: "LAB",
      label: "LDL cholesterol 170 mg/dL",
      detail: "Lipid panel prior to statin initiation.",
      severity: "MODERATE",
    },
    {
      date: "2026-06-01",
      kind: "LAB",
      label: "Creatine kinase 95 U/L",
      detail: "Baseline creatine kinase prior to statin initiation, within reference range (30–200 U/L).",
    },
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
      date: "2026-08-10",
      kind: "LAB",
      label: "LDL cholesterol 98 mg/dL",
      detail: "Lipid panel; marked improvement on statin therapy.",
    },
    {
      date: "2026-08-16",
      kind: "ENCOUNTER",
      label: "Chart prepared for upcoming visit",
      detail: "Pre-visit chart review generated ahead of scheduled follow-up.",
    },
  ],
  labs: [
    {
      analyte: "LDL Cholesterol",
      unit: "mg/dL",
      points: [
        { date: "2024-01-15", value: 175, flag: "HIGH" },
        { date: "2024-07-20", value: 168, flag: "HIGH" },
        { date: "2025-01-10", value: 171, flag: "HIGH" },
        { date: "2025-07-14", value: 165, flag: "HIGH" },
        { date: "2026-06-01", value: 170, flag: "HIGH" },
        { date: "2026-08-10", value: 98 },
      ],
    },
    {
      analyte: "Creatine Kinase",
      unit: "U/L",
      points: [
        { date: "2025-01-10", value: 88 },
        { date: "2026-06-01", value: 95 },
      ],
    },
  ],
};

// Safety-demonstration patient: kept as a FAILED run so the app visibly
// demonstrates that a processing failure renders a distinct, unmistakable
// error state and never a silent "no findings" — see ErrorState.tsx and the
// "Safety demonstration" banner in PatientView/ErrorState/PatientCard.
// Patient history + labs below represent what would have been pulled from
// the source chart for manual review even though the AI pipeline failed
// before it could analyze them; the INR spike is a case that automated
// review never got the chance to flag, which is the whole point.
const meeraIyer: PatientRun = {
  runId: "run-5e19-meera",
  patientId: "MRN-77241",
  patientName: "Meera Iyer",
  status: "FAILED",
  stage: "EVIDENCE_RETRIEVAL",
  findings: [],
  timeline: [
    {
      date: "2024-04-02",
      kind: "DIAGNOSIS",
      label: "Atrial fibrillation diagnosed",
      detail: "New-onset atrial fibrillation identified on routine ECG; anticoagulation therapy planned.",
    },
    {
      date: "2024-04-09",
      kind: "MEDICATION",
      label: "Warfarin 5 mg daily started",
      detail: "Initiated for stroke prevention in atrial fibrillation; INR monitoring scheduled.",
    },
    {
      date: "2024-05-01",
      kind: "LAB",
      label: "INR 2.3",
      detail: "Within therapeutic range (goal 2.0–3.0).",
    },
    {
      date: "2024-11-15",
      kind: "LAB",
      label: "INR 2.5",
      detail: "Within therapeutic range (goal 2.0–3.0).",
    },
    {
      date: "2025-05-20",
      kind: "LAB",
      label: "INR 2.1",
      detail: "Within therapeutic range (goal 2.0–3.0).",
    },
    {
      date: "2025-11-18",
      kind: "LAB",
      label: "INR 2.4",
      detail: "Within therapeutic range (goal 2.0–3.0).",
    },
    {
      date: "2026-07-28",
      kind: "MEDICATION",
      label: "Amiodarone 200 mg daily started",
      detail: "Added for rate control of recurrent atrial fibrillation episodes.",
    },
    {
      date: "2026-08-10",
      kind: "LAB",
      label: "INR 4.1",
      detail:
        "Markedly above therapeutic range; amiodarone is a known potentiator of warfarin's anticoagulant effect.",
      severity: "CRITICAL",
    },
    {
      date: "2026-08-17",
      kind: "ENCOUNTER",
      label: "Chart prep run started",
      detail: "Automated pre-visit chart preparation queued.",
    },
  ],
  labs: [
    {
      analyte: "INR",
      unit: "ratio",
      points: [
        { date: "2024-05-01", value: 2.3 },
        { date: "2024-11-15", value: 2.5 },
        { date: "2025-05-20", value: 2.1 },
        { date: "2025-11-18", value: 2.4 },
        { date: "2026-08-10", value: 4.1, flag: "CRITICAL" },
      ],
    },
  ],
};

const sanjayRao: PatientRun = {
  runId: "run-c440-sanjay",
  patientId: "MRN-83562",
  patientName: "Sanjay Rao",
  status: "FLAGGED_FOR_REVIEW",
  stage: "CLINICIAN_REVIEW",
  findings: [
    {
      claimId: "claim-sanjay-metformin-renal",
      revisionAttempts: 0,
      claimType: "POSSIBLE_CONCERN",
      statement:
        "Declining renal function (eGFR 42 mL/min/1.73m²) in a patient continuing metformin 1000 mg twice daily approaches the threshold where FDA labeling recommends dose reduction and increased monitoring for lactic acidosis risk.",
      severity: "HIGH",
      verdict: "REQUIRES_REVIEW",
      rationale:
        "eGFR has declined from 71 to 42 mL/min/1.73m² over the past two years while metformin dosing has remained unchanged at 1000 mg twice daily. The FDA label for metformin recommends reassessing benefits and risks of continued use when eGFR falls below 45 mL/min/1.73m², and metformin is contraindicated below 30 mL/min/1.73m² due to lactic acidosis risk. No dose adjustment or renal-function-based reassessment is documented in the chart.",
      recommendedAction:
        "Consider reducing metformin dose, increasing renal function monitoring frequency, or evaluating alternative glycemic therapy given the current eGFR trend.",
      patientEvidence: [
        {
          label: "eGFR (BMP)",
          detail: "42 mL/min/1.73m² on 2026-08-05 (prior reading 48 mL/min/1.73m² on 2026-02-11)",
        },
        {
          label: "Active medication",
          detail: "Metformin 1000 mg PO twice daily, unchanged since 2024-06-10",
        },
        {
          label: "Active diagnosis",
          detail: "Type 2 diabetes mellitus, diagnosed 2024-03-18",
        },
      ],
      externalEvidence: [
        {
          evidenceId: "ev-fda-metformin-label",
          tier: "REGULATORY_LABEL",
          publisher: "U.S. Food & Drug Administration",
          jurisdiction: "US FDA LABEL",
          publicationDate: "2023-08-15",
          version: "Rev. 29",
          sourceUrl: "https://www.accessdata.fda.gov/drugsatfda_docs/label/2023/020357s037lbl.pdf",
          snapshotId: "snap-fda-metformin-2023-08-15-29",
          verbatimSpan:
            "Before initiating metformin hydrochloride tablets and at least annually thereafter, estimated glomerular filtration rate (eGFR) should be assessed. Metformin hydrochloride tablets are contraindicated in patients with an eGFR below 30 mL/minute/1.73 m². Initiation of metformin hydrochloride tablets is not recommended in patients with eGFR below 45 mL/minute/1.73 m².",
          computedStartOffset: 3110,
          computedEndOffset: 3402,
          citationVerdict: "VERIFIED_SPAN",
          gatesPassed: [
            { gate: "Source retrievable", passed: true },
            { gate: "Snapshot hash matches", passed: true },
            { gate: "Span located verbatim", passed: true },
            { gate: "Offsets resolve to span", passed: true },
            { gate: "Publisher allow-listed", passed: true },
          ],
          modelBFinding:
            "The cited span directly supports the claim that FDA labeling ties metformin risk thresholds to eGFR, and that renal function should be reassessed as it declines.",
          modelBShouldReject: false,
          reviewedBy: "clin_rn_5521",
        },
        {
          evidenceId: "ev-guideline-metformin-renal",
          tier: "GUIDELINE",
          publisher: "American Diabetes Association",
          jurisdiction: "United States",
          publicationDate: "2024-01-01",
          version: "Standards of Care in Diabetes—2024",
          sourceUrl: "https://diabetesjournals.org/care/issue/47/Supplement_1",
          snapshotId: "snap-ada-standards-2024-01-01-renal",
          verbatimSpan:
            "Metformin dose should be reevaluated when eGFR falls below 45 mL/min/1.73 m², with consideration of dose reduction, increased monitoring, or discontinuation as renal function continues to decline.",
          computedStartOffset: 5602,
          computedEndOffset: 5824,
          citationVerdict: "VERIFIED_SPAN",
          gatesPassed: [
            { gate: "Source retrievable", passed: true },
            { gate: "Snapshot hash matches", passed: true },
            { gate: "Span located verbatim", passed: true },
            { gate: "Offsets resolve to span", passed: true },
            { gate: "Publisher allow-listed", passed: true },
          ],
          modelBFinding:
            "The span supports reassessment of metformin dosing tied to the same eGFR threshold cited in the claim.",
          modelBShouldReject: false,
          reviewedBy: null,
        },
      ],
    },
    {
      claimId: "claim-sanjay-a1c-suboptimal",
      revisionAttempts: 0,
      claimType: "CLINICIAN_REVIEW_SUGGESTION",
      statement:
        "Hemoglobin A1c of 8.2% despite over a year on maximal metformin therapy suggests glycemic control is not at goal and may warrant treatment intensification.",
      severity: "MODERATE",
      verdict: "PARTIALLY_VERIFIED",
      rationale:
        "Hemoglobin A1c has remained above the general goal of <7% (individualized targets may vary) across the last three measurements despite unchanged maximal-dose metformin therapy, suggesting current therapy alone may be insufficient.",
      recommendedAction:
        "Consider discussing add-on glycemic therapy at the upcoming visit, taking the current renal function trend into account when selecting an agent.",
      patientEvidence: [
        {
          label: "Hemoglobin A1c",
          detail: "8.2% on 2026-08-05 (goal individualized, generally <7%)",
        },
        {
          label: "Hemoglobin A1c",
          detail: "7.9% on 2026-02-11",
        },
      ],
      externalEvidence: [
        {
          evidenceId: "ev-guideline-a1c-goal",
          tier: "GUIDELINE",
          publisher: "American Diabetes Association",
          jurisdiction: "United States",
          publicationDate: "2024-01-01",
          version: "Standards of Care in Diabetes—2024",
          sourceUrl: "https://diabetesjournals.org/care/issue/47/Supplement_1",
          snapshotId: "snap-ada-standards-2024-01-01-a1c",
          verbatimSpan:
            "A reasonable A1C goal for many nonpregnant adults is <7%. Consider intensification of therapy in patients not meeting individualized glycemic targets.",
          computedStartOffset: 1820,
          computedEndOffset: 1958,
          citationVerdict: "VERIFIED_SPAN",
          gatesPassed: [
            { gate: "Source retrievable", passed: true },
            { gate: "Snapshot hash matches", passed: true },
            { gate: "Span located verbatim", passed: true },
            { gate: "Offsets resolve to span", passed: true },
            { gate: "Publisher allow-listed", passed: true },
          ],
          modelBFinding:
            "The span supports a general A1c goal of <7% and intensification when unmet, consistent with the claim.",
          modelBShouldReject: false,
          reviewedBy: "PENDING",
        },
      ],
    },
  ],
  timeline: [
    {
      date: "2024-03-18",
      kind: "DIAGNOSIS",
      label: "Type 2 diabetes mellitus diagnosed",
      detail: "Diagnosed following elevated fasting glucose and confirmatory HbA1c of 7.6%.",
    },
    {
      date: "2024-03-18",
      kind: "MEDICATION",
      label: "Metformin 500 mg twice daily started",
      detail: "Initiated as first-line therapy for type 2 diabetes.",
    },
    {
      date: "2024-03-18",
      kind: "LAB",
      label: "eGFR 71 mL/min/1.73m²",
      detail: "Baseline renal function at diagnosis.",
    },
    {
      date: "2024-06-10",
      kind: "MEDICATION",
      label: "Metformin increased to 1000 mg twice daily",
      detail: "Dose increased for improved glycemic control.",
    },
    {
      date: "2024-09-22",
      kind: "LAB",
      label: "eGFR 65 mL/min/1.73m²",
      detail: "Basic metabolic panel; mild decline in renal function.",
    },
    {
      date: "2025-03-14",
      kind: "LAB",
      label: "Hemoglobin A1c 7.8%",
      detail: "Above individualized goal despite maximal metformin dose.",
    },
    {
      date: "2025-03-14",
      kind: "LAB",
      label: "eGFR 58 mL/min/1.73m²",
      detail: "Basic metabolic panel; continued gradual decline in renal function.",
    },
    {
      date: "2025-08-19",
      kind: "ENCOUNTER",
      label: "Follow-up visit",
      detail: "Diabetes and renal function reviewed; lifestyle counseling reinforced.",
    },
    {
      date: "2026-02-11",
      kind: "LAB",
      label: "eGFR 48 mL/min/1.73m²",
      detail: "Basic metabolic panel; renal function approaching metformin reassessment threshold.",
      severity: "MODERATE",
    },
    {
      date: "2026-02-11",
      kind: "LAB",
      label: "Hemoglobin A1c 7.9%",
      detail: "Remains above individualized goal.",
    },
    {
      date: "2026-08-05",
      kind: "LAB",
      label: "eGFR 42 mL/min/1.73m²",
      detail: "Basic metabolic panel; renal function below the FDA-labeled reassessment threshold for metformin.",
      severity: "HIGH",
    },
    {
      date: "2026-08-05",
      kind: "LAB",
      label: "Hemoglobin A1c 8.2%",
      detail: "Glycemic control remains above individualized goal.",
      severity: "MODERATE",
    },
    {
      date: "2026-08-12",
      kind: "ENCOUNTER",
      label: "Chart prep run started",
      detail: "Automated pre-visit chart preparation queued.",
    },
    {
      date: "2026-08-13",
      kind: "ENCOUNTER",
      label: "Chart prepared for upcoming visit",
      detail: "Pre-visit chart review completed ahead of scheduled follow-up.",
    },
  ],
  labs: [
    {
      analyte: "eGFR",
      unit: "mL/min/1.73m²",
      points: [
        { date: "2024-03-18", value: 71 },
        { date: "2024-09-22", value: 65 },
        { date: "2025-03-14", value: 58 },
        { date: "2026-02-11", value: 48, flag: "LOW" },
        { date: "2026-08-05", value: 42, flag: "LOW" },
      ],
    },
    {
      analyte: "Hemoglobin A1c",
      unit: "%",
      points: [
        { date: "2024-03-18", value: 7.6, flag: "HIGH" },
        { date: "2025-03-14", value: 7.8, flag: "HIGH" },
        { date: "2026-02-11", value: 7.9, flag: "HIGH" },
        { date: "2026-08-05", value: 8.2, flag: "HIGH" },
      ],
    },
    {
      analyte: "Creatinine",
      unit: "mg/dL",
      points: [
        { date: "2024-03-18", value: 1.0 },
        { date: "2025-03-14", value: 1.3 },
        { date: "2026-02-11", value: 1.5, flag: "HIGH" },
        { date: "2026-08-05", value: 1.7, flag: "HIGH" },
      ],
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
