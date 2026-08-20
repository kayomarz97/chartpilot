#!/usr/bin/env bash
# scripts/check_no_sampling_params.sh
#
# Gate: Gemini 3.x deprecates temperature/top_p/top_k (see
# research/gemini-notes.md §5 -- Google's own current guidance is to remove
# these entirely, not pin them to 0, and rely on a fixed system instruction
# for determinism instead). This script fails `make check` if any real
# keyword-argument usage of temperature/top_p/top_k appears anywhere under
# backend/app, so nobody reintroduces a sampling parameter by habit.
#
# Excludes: comment lines (first non-space char is '#') and this script
# itself (which necessarily mentions the parameter names in prose above).

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO_ROOT"

PATTERN='\b(temperature|top_p|top_k)[[:space:]]*='

FOUND=0

while IFS= read -r -d '' file; do
  while IFS=: read -r line_no content; do
    # Skip comment-only lines (first non-space char is '#').
    trimmed="$(echo "$content" | sed -e 's/^[[:space:]]*//')"
    if [[ "$trimmed" == \#* ]]; then
      continue
    fi
    echo "$file:$line_no:$content"
    FOUND=1
  done < <(grep -nE "$PATTERN" "$file" 2>/dev/null || true)
done < <(find backend/app -type f -name '*.py' -print0)

if [[ "$FOUND" -ne 0 ]]; then
  echo "check_no_sampling_params: found real temperature/top_p/top_k usage above" >&2
  exit 1
fi

echo "check_no_sampling_params: no sampling-parameter usage found"
exit 0
