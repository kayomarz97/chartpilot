\
SHELL := /bin/bash
PHASE ?= $(shell cat .current_phase 2>/dev/null || echo 00)
EVIDENCE_DIR := evidence
EVIDENCE_FILE := $(EVIDENCE_DIR)/phase_$(PHASE).txt

.PHONY: check refresh-evidence

check:
	@mkdir -p $(EVIDENCE_DIR)
	@set -o pipefail; \
	{ \
	  echo "$(PHASE)"; \
	  git rev-parse HEAD; \
	  date -u; \
	  echo "----- ruff format --check -----"; \
	  ( cd backend && uv run ruff format --check . ) && echo "[PASS] ruff format --check" || { echo "[FAIL] ruff format --check"; exit 1; }; \
	  echo "----- ruff check -----"; \
	  ( cd backend && uv run ruff check . ) && echo "[PASS] ruff check" || { echo "[FAIL] ruff check"; exit 1; }; \
	  echo "----- mypy -----"; \
	  ( cd backend && uv run mypy app ) && echo "[PASS] mypy" || { echo "[FAIL] mypy"; exit 1; }; \
	  echo "----- pytest -----"; \
	  ( cd backend && uv run pytest tests ) && echo "[PASS] pytest" || { echo "[FAIL] pytest"; exit 1; }; \
	  echo "----- secret_scan -----"; \
	  ( scripts/secret_scan.sh ) && echo "[PASS] secret_scan" || { echo "[FAIL] secret_scan"; exit 1; }; \
	  echo "----- no_sampling_params -----"; \
	  ( scripts/check_no_sampling_params.sh ) && echo "[PASS] no_sampling_params" || { echo "[FAIL] no_sampling_params"; exit 1; }; \
	  echo "----- ALL CHECKS PASSED -----"; \
	} 2>&1 | tee $(EVIDENCE_FILE)

# MANUAL ONLY -- performs real network I/O against openFDA/PubMed and is
# never run as part of `make check` (which must stay hermetic).
refresh-evidence:
	( cd backend && uv run python ../scripts/refresh_evidence.py )
