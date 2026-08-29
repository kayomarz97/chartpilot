# ARCHITECTURE.md: ChartPilot backend map

> **Read this FIRST**: before grepping or broad-reading the codebase. It names every module,
> the load-bearing class/function/variable names, the enum/status values, and the exact commands,
> so navigation is by-the-map, not by exploratory search.
>
> **Keep it TRUE in the same change** (project working-agreement rule): whenever you add/move/rename/
> repurpose a module or change a load-bearing name, enum value, env var, or command, update this file
> in the same commit. A stale map is worse than none.

Root: `/root/projects/doctor_helper/backend`. Conventions: all models are pydantic `BaseModel`
`ConfigDict(frozen=True)` unless noted; enums are `enum.StrEnum` (values are the lowercase strings
below); clinical numbers are `decimal.Decimal`; every datetime is fail-closed tz-aware (naive rejected).

---

## How the system works (the flow)

Nightly **Cloud Scheduler** → `POST /enqueue-run` (`app/api/routes.py`) → one idempotent **Cloud Tasks**
task per patient → `POST /tasks/process-patient` → the per-patient pipeline **`run_patient`**
(`app/pipeline/runner.py`), which chains these stages, **failing closed** at each:

`FETCHING` (`app/fhir`) → `NORMALIZING` (`app/normalize`, builds a `PatientFactIndex`) →
`RULES_EVALUATED` (`app/rules` + `app/validation`) → `EVIDENCE_RETRIEVAL` (`app/evidence`, an
immutable hashed snapshot) → `AI_REASONING` (**Model A**, `app/agent`, emits `Claim`s with verbatim
spans) → `CITATION_CHECK` (deterministic gates 1-4, `app/citation`) → `INDEPENDENT_REVIEW`
(**Model B** blinded adversary, `app/review`) → `FINAL_VALIDATION` (`app/gate`, fail-closed verdict) →
`PERSISTED` (two-phase Firestore commit, `app/storage`). A public read-only `GET /runs/{run_id}`
serves the persisted **presentation** read-model to the Next.js UI. In the UI, a clinician may attach
a **CONFIRM/OVERRIDE/CORRECT label** to any finding (Phase B, `app/feedback`); that label plus the
automated per-finding signals already on `FindingResult` (citation verdict, Model B verdict, revision
attempts) are the outer self-improving loop's (Phase C, `app/improve`) training signal. `POST
/improve-run` (OIDC) runs one improvement cycle on demand for a given `run_id`; nothing calls it
automatically yet (no Cloud Scheduler job wired for it). See the section below.

**The safety invariant (SPEC §53):** deterministic code owns every fact; free text is `trusted=False`
and can never mutate a fact/rule/gate; a claim that fails any gate can never be `VERIFIED`; failures
surface as a status (`FAILED`/`FLAGGED_FOR_REVIEW`), never a silent "no findings."

---

## File map (by subpackage, what it does / when to touch it)

### Pipeline orchestration: `app/pipeline/`, `app/tasks/`
| Path | Key symbols / when to touch |
|---|---|
| `pipeline/runner.py` | **`run_patient(..., max_revise_iterations=2, model_a_system_instruction=None)`**: the whole chained pipeline for ONE patient; stages via `_mark_stage`, failures via `_failed_result`. Constants `_EXTERNAL_EVIDENCE_REQUIRED_TYPES`, `_ANALYTE_BY_CODE`. `model_a_system_instruction` (Phase C seam): `None` (default) → byte-identical to before, uses the pinned `agent.prompts.MODEL_A_SYSTEM_INSTRUCTION`; a string → used INSTEAD for the AI_REASONING turn only (the Phase A revise loop below always keeps its own fixed `MODEL_A_REVISE_INSTRUCTION` regardless): this is what lets `app.improve.evaluator_live.build_live_pipeline_score_fn` run a candidate prompt against a real patient without mutating the pinned constant. Per-claim, after the first `run_deterministic_layer`, `_revise_claim_if_eligible` runs the bounded Phase A "gate-failure → revise → retry" loop (`_is_revise_eligible`, `_revision_is_safe` guard, `app.agent.revise`) before Model B/the final gate; `claims_payload` is built from the FINAL (possibly revised) claims, never the originals. **Start here for pipeline-flow changes.** |
| `pipeline/models.py` | Result DTOs: **`PatientRunResult`** (`.summary`, `.findings`, `.rule_results`, `.validity_results`, `.timeline_events`, `.error`), **`FindingResult`** (`.claim`, `.verdict`, `.citation_results`, `.model_b_verdict`, `.revision_attempts`, Phase A trace field, default `0`), **`PatientRunSummary`**. |
| `pipeline/precomputed.py` | **`build_precomputed_run(...)`** / **`load_precomputed_run(...)`**: 5 demo patients A-E, fixed clock `_DEFAULT_NOW`. Type aliases `ModelAFactory`, `ModelBFactory`. |
| `tasks/orchestrator.py` | **`process_patient(task, *, store, budget, stage_runners, finalize, clock)`**: idempotent + resumable + budgeted; dead-letters on retry-exhaust, `TIMED_OUT` on budget-exceed. |
| `tasks/enqueue.py` | **`enqueue_run(*, run_id, appointment_source, queue, clock)`** → `EnqueueResult`; one `RunTask` per patient appointed tomorrow (IST). |
| `tasks/queue.py` | **`TaskQueue`** Protocol (`enqueue(task)->bool`, True=new/False=dedup); `InMemoryTaskQueue`. `cloud_tasks.py` = live adapter. |
| `tasks/models.py` | **`RunTask`** (`.task_name` = `f"{run_id}:{patient_id}"` idempotency key), **`ExecutionBudget.default()`**, **`BudgetCounters.first_exceeded(budget)`**, **`Checkpoint`** (`.completed_stages`, `.current_stage`). |

### FHIR + Normalize: `app/fhir/`, `app/normalize/`
| Path | Key symbols |
|---|---|
| `fhir/client.py` | **`FhirClient(transport, *, max_pages=50, max_resources=5000)`** → `.fetch_all(ref)`, `.iter_resources(ref)`. Raises `MalformedBundleError`, `FhirPaginationError`, `FhirResourceLimitError`. |
| `normalize/observation.py` | **`normalize_observation(resource)->NormalizedObservation`** (never raises on bad unit → `normalization_warnings`); **`latest_valid_observation(obs, *, code)`** (supersession-aware). |
| `normalize/units.py` | **`normalize_quantity(analyte, value, unit)->NormalizedQuantity`** (raises `UnitNormalizationError`). `_REGISTRY`: potassium/sodium→`mmol/L`, creatinine→`mg/dL`. |
| `normalize/temporal.py` | **`parse_fhir_datetime(raw)->ClinicalInstant`**, **`compare(a,b)->Ordering`**. `DISPLAY_TZ=ZoneInfo("Asia/Kolkata")`. Enums `Precision`, `Ordering`. Time-of-day requires offset (fail-closed). |
| `normalize/models.py` | **`NormalizedObservation`**, `NormalizedComponent`, `ReferenceRange`, `NarrativeNote(trusted=False)`. Enums `ObservationStatus`, `AbnormalityBasis`. |
| `normalize/medication.py` | `NormalizedMedicationOrder` (`.medication_display`, `.is_active_order`, `.authored_on`). |
| `normalize/adr.py` | `NormalizedAdverseReaction` (`.causative_agent`, `.manifestation`). |

### Rules + validation: `app/rules/`, `app/validation/`
| Path | Key symbols |
|---|---|
| `rules/potassium.py` | **`evaluate_k_high_risk(observations, medications, *, config, med_classes, evaluated_at)->RuleResult`**. Constant **`RULE_ID="K_HIGH_RISK_001"`**. `KHighRiskConfig` from `rules/data/rules.toml` (`high_mmol_l=5.5`, `critical_mmol_l=6.0`). **FROZEN clinical logic.** |
| `rules/models.py` | Enums `RuleVerdict`, `Severity`; **`RuleResult`**, `AbnormalityAssessment`. |
| `rules/medication_classes.py` | `MedicationClasses` (potassium-raising drug list). |
| `validation/engine.py` | **`ClinicalValidityEngine`** (`.register`, `.evaluate(metric_id, inputs)`); unknown→`NOT_APPLICABLE`, missing input→`INSUFFICIENT_DATA`. |
| `validation/metrics.py` | **`build_default_engine()`**; metric ids `EGFR_METRIC_ID="egfr_ckd_epi_2021_cr"`, `CORRECTED_CALCIUM_METRIC_ID`, `ANION_GAP_METRIC_ID`. **FROZEN clinical math.** |
| `validation/models.py` | Enum `ValidityStatus`; `ValidityContract`, **`ValidityResult`**. |

### Evidence: `app/evidence/`
| Path | Key symbols |
|---|---|
| `evidence/snapshot.py` | **`build_snapshot(records, *, created_at)->EvidenceSnapshot`** (caps `MAX_LITERATURE_RECORDS=150`, `MAX_GUIDELINE_RECORDS=15`); **`persist_snapshot(...)`** write-once (`SnapshotImmutableError`). |
| `evidence/openfda.py` | **`fetch_label(ingredient, *, http_get, ...)`**, `select_label` (§14 SPL), `label_to_record` (tier `REGULATORY_LABEL`, jurisdiction `US_FDA`). |
| `evidence/pubmed.py` | **`esearch(...)`** / **`efetch(...)`** (tier `LITERATURE`). Rates `DEFAULT_RATE_NO_KEY=3.0`, `DEFAULT_RATE_WITH_KEY=10.0`. |
| `evidence/guideline_citations.py` | **`search_and_fetch_guideline_citations(...)`**: `GUIDELINE_PUBLICATION_TYPE_TERM='"guideline"[Publication Type]'`; re-tiers to `GUIDELINE`, `metadata["reviewed_by"]="PENDING"` (caps verdict). |
| `evidence/models.py` | **`EvidenceRecord`** (`.content`, `.content_hash`), **`EvidenceSnapshot`** (`.get(id)`, `.manifest_hash`). Enums `EvidenceTier`, `Jurisdiction`. |
| `evidence/hashing.py` | **`content_hash(text)`** (sha256), **`snapshot_id(records)`** (order-independent). |

### Model A / agent: `app/agent/`
| Path | Key symbols |
|---|---|
| `agent/gemini.py` | **`GeminiInteractionsClient(*, api_key, model_id, max_retries=3, ...)`**: real `google-genai` adapter; `.create(*, input, response_schema=None, ...)`, `.list_models()`. **NO temperature/top_p/top_k.** |
| `agent/prompts.py` | **`MODEL_A_SYSTEM_INSTRUCTION`** (module constant, byte-identical determinism). **This is the AUTO-tier prompt the self-improving loop may tune.** Also **`MODEL_A_REVISE_INSTRUCTION`**: the fixed instruction for the Phase A revise loop below (re-quote a citation span only, never change clinical meaning). |
| `agent/claims.py` | **`generate_claims(client, *, model_system_instruction, user_input)->ClaimSet`**; `claim_response_schema()`, `parse_claim_set(raw)` (raises `StructuredOutputError`). |
| `agent/revise.py` | Phase A inner "gate-failure → revise → retry" loop (spec §53). **`build_revision_hint(claim, citation_results, snapshot)->str \| None`**: deterministic hint listing each span-repairable citation's rejected span + full source text; `None` if nothing is repairable. **`revise_claim(client, *, claim, revision_hint)->Claim`**: one Model A turn re-quoting the failing span(s), structured output against `Claim.model_json_schema()`. Re-exports **`is_span_repairable`** from `app/citation/verifier.py`. |
| `agent/models.py` | **`Claim`** / **`ClaimSet`** (`extra="forbid"`), `ExternalEvidenceRef` (`verbatim_supporting_span`, **no offset field**), `PatientEvidenceRef`. Enum `ClaimType` (7 values). |
| `agent/model_pin.py` | **`load_model_pin()`**, **`verify_pinned_models(client, pin)`** (fails loud `ModelResolutionError`). Reads `config/models.yaml`. |
| `agent/protocol.py` | **`GeminiClient`** Protocol (the seam both models implement), `InteractionResult`, `FunctionCall`. No sampling params by design. |

### Citation gates: `app/citation/`
| Path | Key symbols |
|---|---|
| `citation/verifier.py` | **`verify_citation(ref, *, snapshot, claim_type)->CitationResult`**: Gates 1-4 (SOURCE_RETRIEVAL → CONTENT_HASH → SPAN_VERIFICATION → METADATA). **Offsets computed by us**, into NORMALIZED text. `offsets_still_valid(result, current_record)`. **`is_span_repairable(result)->bool`**: SOURCE_RETRIEVAL/CONTENT_HASH/METADATA all passed but SPAN_VERIFICATION failed; the Phase A revise-loop eligibility predicate (`app/agent/revise.py`, `app/pipeline/runner.py`). |
| `citation/models.py` | Enums `CitationVerdict` (`verified_span`/`reject`/`flag_for_review`), `GateName`; **`CitationResult`** (`.verdict`, `.gates`, `.computed_start_offset`, `.artifact_content_hash`), `GateResult`. |
| `citation/normalization.py` | `normalize_text(...)`: the canonical form spans are matched against. |

### Model B review: `app/review/`
| Path | Key symbols |
|---|---|
| `review/reviewer.py` | **`run_model_b(client, packet)->ModelBVerdict`** (raises `ModelBOutputError`). |
| `review/prompts.py` | **`MODEL_B_SYSTEM_INSTRUCTION`** (adversarial blinded reviewer constant). |
| `review/deterministic.py` | **`run_deterministic_layer(cur, *, snapshot)->DeterministicOutcome`**: runs BEFORE Model B; `blocked` iff any integrity failure OR citation `REJECT` (FLAG_FOR_REVIEW does not block). |
| `review/integrity.py` | **`check_patient_fact_integrity(cur)->list[IntegrityFailure]`**: mechanical resource/number/date/drug checks. |
| `review/corruption.py` | §22 measurement: **`measure_suite(...)->SuiteReport`**, **`release_threshold_met(report)`**; `SET_D_CORRUPTIONS` (7 deterministic), `SET_M_CORRUPTIONS` (8 model-only). **The frozen benchmark the outer loop scores against.** |
| `review/models.py` | **`ModelBPacket`** (BLINDED, no Model A rationale/confidence), **`ModelBVerdict`** (`.finding`, `.should_reject`), `ClaimUnderReview`, `PatientFactIndex`, `SuiteReport`. Enums `ReviewFinding`, `IntegrityFailureKind`. |

### Final gate: `app/gate/`
| Path | Key symbols |
|---|---|
| `gate/claim_gate.py` | **`finalize_claim_verdict(...)->ClaimVerdict`**: fixed order; citation `REJECT` → `REJECTED` **never overridable by Model B** (§65.4); pending guideline caps at `PARTIALLY_VERIFIED`. **FROZEN: fail-closed. Do not loop/auto-tune.** |
| `gate/patient_state.py` | **`derive_patient_status(...)->PatientStatus`**, `can_advance_stage(cur, target)` (monotonic), `assert_state_invariants(state)` (raises `StateInvariantError`). |
| `gate/models.py` | Enums **`ClaimVerdict`**, **`PatientStatus`**, **`PatientStage`** (+ `STAGE_ORDER`), `CommitStatus`; `is_terminal(status)`. |

### Storage: `app/storage/`
| Path | Key symbols |
|---|---|
| `storage/two_phase.py` | **`finalize_patient_result(repo, *, run_id, patient_id, ..., claims, evidence, terminal_status)->PatientSummary`**: §45A PREPARE→WRITE→COMMIT; `reconcile(...)`, `is_result_complete(summary)`. |
| `storage/repository.py` | **`RunRepository`** Protocol (`upsert_patient_summary`, `write_documents`, `read_documents`, `upsert_presentation`, `list_presentations`, `get_patient_summary`). |
| `storage/firestore_repo.py` | **`FirestoreRunRepository(*, project, database)`**: live Admin SDK. Marked `# VERIFY-LIVE`. |
| `storage/inmemory.py` | **`InMemoryRunRepository(*, fail_after_writes=None)`**: hermetic fake (`FaultInjected`). Use in tests. |
| `storage/models.py` | **`PatientSummary`**; path helpers `patient_summary_path`, `claims_collection_path`, `evidence_collection_path`, `presentations_collection_path`, `clinician_actions_collection_path` (Phase B, `runs/{run_id}/patients/{patient_id}/clinician_actions`); `chunk_documents(docs, max_size=400)`, `MAX_WRITES_PER_BATCH=400`. |

### Clinician feedback: `app/feedback/` (Phase B, spec §53)
| Path | Key symbols |
|---|---|
| `feedback/models.py` | **`ClinicianAction(BaseModel, frozen, extra="forbid")`**: one clinician label on one claim: `action_id` (client-supplied idempotency key = Firestore doc id), `run_id`, `patient_id`, `claim_id`, `action: ClinicianActionKind`, `note: str = ""` (**`trusted: Literal[False] = False`**, a label, never a fact/rule/gate input), `verdict_shown: str \| None`, `recorded_at` (tz-aware; naive rejected). Enum **`ClinicianActionKind`**: `confirm, override, correct`. Persisted via the generic `RunRepository.write_documents` (no new Protocol method), read via `app.api.routes.record_clinician_action`. |

### Outer self-improving loop: `app/improve/` (Phase C, spec §53, IMPLEMENTED)
| Path | Key symbols / when to touch |
|---|---|
| `improve/models.py` | **`ImproveTarget(StrEnum)`**: the ONLY AUTO-tunable targets: `model_a_prompt`, `evidence_ranking`. **`FROZEN_TARGET_NAMES`**: documented known-forbidden identifiers (enforcement is default-deny, not this list). `TrainingCase`, **`case_is_automated_flag(case)`**, `Dataset` (`.failure_museum`, `.split()->(train, holdout)`, deterministic SHA-256-of-`claim_id` partition, no RNG), `Candidate` (`extra="forbid"`), `Metrics`, `EvaluationResult`, `PromotionRecord`, `ImprovementReport`. |
| `improve/errors.py` | `ImproveError`, **`FrozenTargetError`**: the hard stop. |
| `improve/collector.py` | **`collect_dataset(*, presentations, clinician_actions)->Dataset`**: pure join of `list_presentations` output + clinician-action docs by `(patient_id, claim_id)`, defensive `.get(...)` throughout. |
| `improve/proposer.py` | **`assert_target_allowed(target: str)`**: the default-deny guard, raises `FrozenTargetError`; called at proposal entry AND again on the returned candidate's target (defense in depth). `AUTO_TIER_TARGETS`, `Generator` type alias, **`propose_candidate(dataset, *, target, generate)`**: calls `generate` on the TRAIN split ONLY. |
| `improve/proposer_llm.py` | **`LlmProposer(client, *, current_prompt)`**: the REAL, LLM-backed `Generator` for `ImproveTarget.MODEL_A_PROMPT`: one structured-output Gemini turn (schema `ProposerOutput`, `new_value`/`rationale` only, no `target` field, mirrors `app.agent.claims`'s call/parse pattern) sending `PROPOSER_SYSTEM_INSTRUCTION` + `current_prompt` + a bounded `dataset.failure_museum` summary; always hardcodes `Candidate.target=ImproveTarget.MODEL_A_PROMPT` in code (never model-chosen). Raises `improve.errors.ProposerOutputError` on invalid model output. LIVE (token-costing); wired by `app.api.composition.get_improve_generator`. |
| `improve/evaluator.py` | `ScoreFn` type alias, **`compare_metrics(before, after)->(improved, regressed)`** (higher set_d_blocked/set_m_caught/clinician_agreement better, higher false_reject worse; ANY regression blocks), **`evaluate_candidate(candidate, *, active_value, score_fn)`** (`accept = improved and not regressed`), **`build_benchmark_score_fn(dataset_holdout)->ScoreFn`**: the concrete hermetic default (frozen §22 corruption suite via a fixed fixture + reference Model-B stand-in, plus holdout `clinician_agreement`; **never varies with the candidate value**, no live model call, see its docstring). **`clinician_agreement_from_holdout(dataset_holdout)->float`**: public, also reused by `evaluator_live.py`. |
| `improve/evaluator_live.py` | **`build_live_pipeline_score_fn(*, benchmark, run_pipeline, dataset_holdout=None)->ScoreFn`**: the REAL, LIVE default: runs every benchmark patient id through the injected `run_pipeline` (closes over `run_patient(model_a_system_instruction=candidate)`). **PRIMARY objective = the review-survival rate** (`_review_survival_counts`/`_survives_review`): of all cited findings, the fraction whose citations all `VERIFIED_SPAN` AND whose blinded Model-B verdict is `SUPPORTED`/not `should_reject`: the axis with real headroom (baseline ~59%; citation-span rate is saturated at 100%). Encoded as basis points: `Metrics.set_d_blocked`=review-survival (higher better), `false_reject`=`10000-set_d_blocked` (derived). **GUARD = citation verified-span rate** on `Metrics.set_m_caught` (higher better): a candidate that lifts review-survival by DROPPING citation quality regresses this axis and is rejected. `clinician_agreement` from `evaluator.clinician_agreement_from_holdout` or neutral `1.0`. Empty candidate `""` (the "nothing promoted yet" sentinel) → `None` so the pinned default scores the baseline. LIVE (token-costing); wired by `app.api.composition.get_improve_score_fn`. |
| `improve/ledger.py` | **`PromotionLedger`**: structural `Protocol` (mirrors `app.storage.repository.RunRepository`): `.active(target)`, `.active_value(target)`, `.promote(target, value, *, version, rationale, now)`, `.rollback(target)`. `safe_ledger_component(raw)->str`: shared path/doc-id sanitizer used by both concrete backends below. `resolve_artifact`/`run_improvement_cycle` depend ONLY on this Protocol, never a concrete class. |
| `improve/promote.py` | **`FilePromotionLedger(base_dir)`**: append-only, file-backed `PromotionLedger` implementation (hermetic-test default; construct with pytest `tmp_path`, never a real dir). **`canary_compare(candidate_value, active_value, *, score_fn)->bool`**: second independent regression check before promotion. |
| `improve/inmemory_ledger.py` | **`InMemoryPromotionLedger()`**: dict-backed hermetic `PromotionLedger` fake (mirrors `app.storage.inmemory.InMemoryRunRepository`); no disk, no network. |
| `improve/firestore_ledger.py` | **`FirestorePromotionLedger(*, project, database)`**: the DURABLE production `PromotionLedger`, live Admin SDK (same lazy `firestore.Client(...)` construction as `FirestoreRunRepository`). Marked `# VERIFY-LIVE`, never touched by the hermetic suite. Doc layout: `improve/{target}` pointer doc (`active_version`, `previous_version`) + `improve/{target}/versions/{version}` (artifact `value` + `PromotionRecord` fields); `promote` writes the version doc then flips the pointer, `rollback` swaps `active_version`/`previous_version` (single-level undo). Survives Cloud Run instance restarts/redeploys/scale-to-zero and is shared across every concurrently-running instance; it supersedes `FilePromotionLedger`'s local-disk-only storage for production. |
| `improve/registry.py` | **`resolve_artifact(target, default, *, ledger=None)->str`**: empty/`None` ledger returns `default` byte-identical. Wired into the LIVE per-patient worker path via `app.api.composition.live_process_patient_handler` (see below and "self-improving loop" section). |
| `improve/cycle.py` | **`run_improvement_cycle(*, presentations, clinician_actions, target, generate, score_fn, ledger, now, version)->ImprovementReport`**: collect → split → propose(train) → evaluate(holdout) → canary → promote; wraps propose/evaluate and canary/promote in `try/except Exception`, fail-closed (never raises, never promotes on uncertainty). `ledger` is typed as the `PromotionLedger` Protocol. |

### API + config: `app/api/`, `app/config.py`, `app/main.py`
| Path | Key symbols |
|---|---|
| `api/routes.py` | **`router`**; `POST /enqueue-run` + `POST /tasks/process-patient` (OIDC via `require_oidc`); **`GET /runs/{run_id}` PUBLIC** (returns `list_presentations`, `[]` not 404 for unknown); **`POST /runs/{run_id}/patients/{patient_id}/clinician-action`** (Phase B, OIDC via `require_oidc`): persists one `ClinicianAction` (body: `claim_id, action, note="", verdict_shown=None, action_id`) via `write_documents(clinician_actions_collection_path(...), ...)`, `action_id` as doc id for idempotent re-submit; reached only via the frontend's authenticated proxy, never a direct browser call. **`POST /improve-run`** (Phase C, OIDC via `require_oidc`): body `run_id, target=model_a_prompt, version`; reads `list_presentations(run_id)` + every patient's `clinician_actions` subcollection, runs `app.improve.cycle.run_improvement_cycle`, returns its `ImprovementReport`; its only possible write is an append to the injected `PromotionLedger`, on acceptance only. DI providers `get_queue`, `get_run_repository`, `get_process_patient_handler`, `get_clock`, `get_improve_generator`/`get_improve_score_fn` (from `app.api.composition`), `get_improve_ledger` (`FirestorePromotionLedger(project=settings.gcp_project_id, database=settings.firestore_database)`: the same durable backend `live_process_patient_handler` reads from, so a promotion made here is visible to every Cloud Run instance and survives restarts/redeploys; tests override with `InMemoryPromotionLedger`/`FilePromotionLedger(tmp_path)`). |
| `api/presentation.py` | **`build_presentation(result, *, patient_name)->dict`**: camelCase UI payload (`patientId/status/findings/timeline/labs`; each finding also carries `revisionAttempts` from `FindingResult.revision_attempts`, Phase B). Pure. `_LAB_THRESHOLDS` (potassium/sodium/creatinine/egfr, egfr `inverted`). |
| `api/composition.py` | **`live_process_patient_handler(task)`** (prod wiring: real Gemini + Firestore; as of Phase C step (b), also resolves the LIVE Model-A prompt from the promotion ledger via `_resolve_live_model_a_system_instruction(settings)`: `FirestorePromotionLedger(project=settings.gcp_project_id, database=settings.firestore_database)` + `resolve_artifact(ImproveTarget.MODEL_A_PROMPT, MODEL_A_SYSTEM_INSTRUCTION, ledger=...)`, fail-safe on any ledger error, DURABLE across Cloud Run instance restarts/redeploys/scale-to-zero and shared across every concurrently-running instance, see `improve/firestore_ledger.py`'s row above), **`run_demo_patient(..., model_a_system_instruction=None)`** (hermetic; the param passes straight through to `run_patient`, `None` byte-identical to before), `build_run_repository`, `build_live_queue`, `DEMO_PATIENT_IDS`. Phase C, both **`# VERIFY-LIVE`** (real, token-costing network calls; never called by the hermetic suite): **`get_improve_generator()->Generator`** builds `app.improve.proposer_llm.LlmProposer` against a real Model-A Gemini client, `current_prompt=agent.prompts.MODEL_A_SYSTEM_INSTRUCTION` (the pinned default, does NOT read the promotion ledger yet, see its docstring); **`get_improve_score_fn()->Callable[[Dataset], ScoreFn]`** builds `app.improve.evaluator_live.build_live_pipeline_score_fn` over `DEMO_PATIENT_IDS`, with `run_pipeline` closing over real Gemini clients + `run_patient(model_a_system_instruction=...)`, the `/improve-run` composition-root providers, now genuinely candidate-dependent (replaces the former no-op placeholder + hermetic `build_benchmark_score_fn` default). |
| `api/auth.py` | `require_oidc`: fails CLOSED if `oidc_audience` unset. |
| `config.py` | **`Settings(BaseSettings)`**, **`get_settings()`** (`@lru_cache`; import never raises; tests call `get_settings.cache_clear()`). |
| `main.py` | **`app = FastAPI(title="ChartPilot Backend")`**; `GET /health` (503 lists `missing_fields` names only). CORS `methods=["GET"]`. `DEFAULT_PORT=8000`. |

### Don't touch / generated
- `app/pipeline/precomputed.py` cassettes + `app/demo_data/`: hand-authored synthetic fixtures.
- `config/models.yaml`: the model **pin of record** (checked against live discovery); change via a decision, not casually.
- `evidence/phase_*.txt`: machine-generated gate output; regenerate via `make check`, never hand-edit.

---

## Enum reference (exact StrEnum values)

- **`PatientStatus`** (`gate/models.py`): `queued, running, completed, partial, flagged_for_review, failed, timed_out, dead_letter`. Non-terminal = {queued, running}.
- **`PatientStage`** (= `STAGE_ORDER`): `queued, fetching, normalizing, rules_evaluated, evidence_retrieval, ai_reasoning, citation_check, independent_review, final_validation, persisted`.
- **`CommitStatus`**: `preparing, committed, partial, failed`.
- **`ClaimVerdict`**: `verified, partially_verified, conflicting, unverifiable, rejected, requires_review`.
- **`CitationVerdict`**: `verified_span, reject, flag_for_review`. **`GateName`**: `source_retrieval, content_hash, span_verification, metadata`.
- **`ReviewFinding`**: `supported, contradicted, overstated, wrong_population, wrong_jurisdiction, stale_source, temporal_issue, omitted_context, insufficient_evidence`.
- **`IntegrityFailureKind`**: `resource_not_found, wrong_patient, numeric_mismatch, wrong_drug, date_mismatch`.
- **`RuleVerdict`**: `fired, not_fired, requires_review, insufficient_data`. **`Severity`**: `critical, high, moderate, low, info`.
- **`ValidityStatus`**: `valid, valid_with_limitations, invalid, insufficient_data, not_applicable, requires_review`.
- **`ClaimType`**: `patient_fact, regulatory_fact, guideline_recommendation, patient_specific_inference, possible_concern, clinician_review_suggestion, uncertainty`.
- **`EvidenceTier`**: `regulatory_label, literature, guideline`. **`Jurisdiction`**: `us_fda, not_applicable`.
- **`ObservationStatus`**: `registered, preliminary, final, amended, corrected, cancelled, entered_in_error, unknown`. **`AbnormalityBasis`**: `reference_range, interpretation, configured_demo_threshold, none`.
- **`Precision`**: `year, month, day, minute, second, millisecond, absent`. **`Ordering`**: `before, after, equal, indeterminate_order`.
- **`CorruptionSet`**: `deterministic, model_only`.

---

## Commands (`Makefile` at repo root)

`PHASE` read from `.current_phase` (default `00`); each `check` teed to `evidence/phase_$(PHASE).txt`
with git SHA + UTC. All run in `backend/` via `uv run`.

```bash
cd backend && uv sync        # install backend deps (once)
make check                   # THE verify gate (hermetic, no network/key):
                             #   ruff format --check → ruff check → mypy app → pytest tests
                             #   → scripts/secret_scan.sh → scripts/check_no_sampling_params.sh
                             #   each step [PASS]/[FAIL]→exit 1. Must exit 0 before "done".
make refresh-evidence        # ⚠️ MANUAL ONLY: real openFDA/PubMed network
make live-test               # ⚠️ MANUAL ONLY: real Gemini, COSTS TOKENS, needs GEMINI_API_KEY
                             #   (runs pytest tests/live -m live)

cd frontend && pnpm install && pnpm run build && pnpm test   # frontend build + axe a11y
```

**CI** (`.github/workflows/ci.yml`): on every push/PR to `main`/`dev`, GitHub Actions installs `uv`
(+ Python 3.11), runs `uv sync --frozen` in `backend/`, then runs the same hermetic `make check`
gate and uploads `evidence/phase_*.txt` as a build artifact. The README's CI badge reflects it.

**Other repo-root files** (not backend modules): `README.md` (narrative + screenshots under `docs/images/`,
incl. `docs/images/gcp/` deployment-proof shots), `LICENSE` (MIT), `CONTRIBUTING.md`, `SUBMISSION.md`
(Devpost copy), `EVALUATION.md`, `TECHNICAL_DECISIONS.md`, `ATTRIBUTION.md`, `journal.md`, `infra/`.

---

## Prompts & model pinning

- Prompts are **Python module constants** (not templates) for byte-identical determinism:
  `agent/prompts.py::MODEL_A_SYSTEM_INSTRUCTION`, `review/prompts.py::MODEL_B_SYSTEM_INSTRUCTION`.
- **No sampling params anywhere** (temperature/top_p/top_k): enforced by
  `scripts/check_no_sampling_params.sh` in `make check`.
- Model IDs pinned in `config/models.yaml`: **`model_a_id: gemini-3.7-flash`**,
  **`model_b_id: gemini-3.5-flash`** (`provider: Gemini Developer API (google-genai)`). Verified at
  startup against live `client.list_models()`; missing id → `ModelResolutionError` (no fallback).
  Runtime clients are built from `Settings.model_a_id`/`model_b_id` (env); the YAML is the
  pin-of-record checked against live discovery.

---

## Config / env vars (`config.py::Settings`, from `.env`, case-insensitive, extra ignored)

- **Required** (missing → `ValidationError`): `gcp_project_id`, `gcp_region`, `model_a_id`,
  `model_b_id`, `gemini_api_key`.
- **Optional**: `allow_synthetic_debug_logs=False`, `display_timezone="Asia/Kolkata"`,
  `oidc_audience=None` (require_oidc fails CLOSED if unset), `tasks_queue`, `worker_url`,
  `tasks_invoker_sa`, `firestore_database`, `frontend_origin` (CORS, comma-separated, default `["*"]`).
- Rule thresholds live separately in `app/rules/data/rules.toml` (`[k_high_risk_001]`
  version=1.0.0, high_mmol_l=5.5, critical_mmol_l=6.0).

---

## Where the self-improving loop (IMPLEMENTED, Phase C) attaches

See `app/improve/` (file map above).
Tier boundary this map enforces, now backed by code (`app/improve/models.py::ImproveTarget`,
`app/improve/proposer.py::assert_target_allowed`):
- **AUTO-tunable** (loop may propose + auto-promote if it beats the frozen benchmark):
  `ImproveTarget.MODEL_A_PROMPT` (`agent/prompts.py`), `ImproveTarget.EVIDENCE_RANKING` (evidence
  retrieval ranking in `app/evidence/`). These are the ONLY two values `ImproveTarget` has.
- **HUMAN-GATED** (loop may propose a diff, human approves; not yet a code path in `app/improve/`):
  Model-B threshold in `review/corruption.py::release_threshold_met`, `ExecutionBudget` values.
- **FROZEN** (loop may never self-apply): `app/rules/`, `app/validation/metrics.py`,
  `gate/claim_gate.py`, `app/normalize/`. `app/improve/proposer.py::assert_target_allowed` raises
  `FrozenTargetError` for any target outside the AUTO allowlist above (default-deny, an
  unrecognized target is refused exactly like a documented FROZEN one); called at BOTH proposal
  entry (`propose_candidate`) and immediately before promotion
  (`PromotionLedger.promote`/`run_improvement_cycle`); defense in depth.

**Training signal (Phase B, already collected):** `app/feedback/models.py::ClinicianAction`
(CONFIRM/OVERRIDE/CORRECT + untrusted note, one per claim, from the UI's per-finding label control
in `frontend/components/ClinicianActionControl.tsx` via the same-origin OIDC proxy
`frontend/app/api/clinician-action/route.ts` → `POST /runs/{run_id}/patients/{patient_id}/
clinician-action`) plus the automated per-finding signals already on `FindingResult`
(`citationVerdict`, `modelBFinding`/`modelBShouldReject`, `verdict`, `revisionAttempts`, all
readable from `list_presentations`/`build_presentation`'s output). `app/improve/collector.py::
collect_dataset` joins both into a `Dataset`; `Dataset.split()` deterministically (SHA-256 of
`claim_id`, no RNG) partitions it into a TRAIN slice (fed to the proposer only) and a HELD-OUT
slice (fed to the evaluator only): enforced in code so the loop can never train on the same cases
it is graded against (the Model-B "game your own number" trap this README calls out elsewhere).

**No training on the held-out eval, in code:** `app/review/corruption.py` (the §22 frozen
benchmark) is never imported by `app/improve/` in a way that mutates it:
`evaluator.py::build_benchmark_score_fn` only calls `measure_suite`/reads `SET_M_CORRUPTIONS`,
exactly like `tests/unit/test_corruption_suite.py` does.

**Determinism preserved, live consumption now wired (Phase C step (b)):**
`agent/prompts.py::MODEL_A_SYSTEM_INSTRUCTION` stays a pinned Python constant;
`app/improve/registry.py::resolve_artifact(target, default, *, ledger=None)` returns the ledger's
active promoted value if one exists, else `default`: an empty ledger (true of every deployment
before its first accepted promotion) is byte-identical to not calling it. `run_patient` accepts an
explicit `model_a_system_instruction` override (`None` default -> the pinned constant, unchanged);
`app.api.composition.run_demo_patient` passes this straight through, defaulting to `None` so every
existing caller is unaffected. Two live consumers now use this seam:
- The LIVE evaluator (`app.improve.evaluator_live.build_live_pipeline_score_fn`) runs a CANDIDATE
  prompt against a real benchmark patient during `POST /improve-run` scoring, unchanged from
  before.
- **`app.api.composition.live_process_patient_handler`** (the actual production per-patient worker
  path, reached via `POST /tasks/process-patient`) now calls a new helper,
  `_resolve_live_model_a_system_instruction(settings)`, which builds a `FirestorePromotionLedger
  (project=settings.gcp_project_id, database=settings.firestore_database)` and resolves
  `ImproveTarget.MODEL_A_PROMPT` through `resolve_artifact` before every patient run, passing the
  result into `run_demo_patient`. An empty ledger resolves back to the pinned constant,
  byte-identical to before this wiring existed; any ledger construction/read error (a Firestore
  auth/permission error, a transient network error, a corrupted record) is caught and also falls
  back to the pinned constant: a ledger problem must never break a patient run.
  **Ledger durability (Firestore):** the promotion ledger is now backed by
  `app.improve.firestore_ledger.FirestorePromotionLedger`, the same durable Admin-SDK pattern as
  `app.storage.firestore_repo.FirestoreRunRepository`, instead of a path on the Cloud Run
  container's local disk. A promotion accepted by `POST /improve-run` therefore DOES durably change
  what production serves: it is visible to every Cloud Run instance (not just the one that served
  that request), and survives instance restarts, redeploys, and scale-to-zero. This supersedes the
  earlier file-backed ledger (`app.improve.promote.FilePromotionLedger`, kept only as the
  hermetic-test default), whose writes lived on one instance's ephemeral local disk and were never
  a trustworthy production lever.

**Fail-closed:** `app/improve/cycle.py::run_improvement_cycle` wraps propose/evaluate and
canary/promote in `try/except Exception`, returning a rejected `ImprovementReport` (never raising,
never promoting) on any error: a bug in a candidate generator or a `ScoreFn` cannot corrupt the
ledger or crash `POST /improve-run`.
