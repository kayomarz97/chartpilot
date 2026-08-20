#!/usr/bin/env bash
# scripts/secret_scan.sh
#
# Simple grep-based secret scanner used by `make check`. Scans tracked and
# working-tree files for obvious secret patterns. Exits non-zero if a
# likely-real secret is found; exits 0 otherwise.
#
# Excludes: .env.example, uv.lock, research/, and common doc/lock files —
# these legitimately contain placeholder-looking strings or are not source
# we author.

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO_ROOT"

# Files to scan: everything git tracks or has staged, plus untracked-but-not-ignored
# working files (so this also catches secrets before they're ever added).
# Fall back to a plain find if not in a git repo.
if git rev-parse --is-inside-work-tree >/dev/null 2>&1; then
  mapfile -t FILES < <(git ls-files --cached --others --exclude-standard)
else
  mapfile -t FILES < <(find . -type f -not -path "./.git/*")
fi

EXCLUDE_REGEX='(^|/)\.env\.example$|(^|/)uv\.lock$|(^|/)research/|(^|/)SPEC\.md$|(^|/)PLAN\.md$|(^|/)RESEARCH\.md$|(^|/)TECHNICAL_DECISIONS\.md$|(^|/)journal\.md$|(^|/)QUESTIONS\.md$|(^|/)ATTRIBUTION\.md$|(^|/)evidence/|(^|/)\.git/'

SCAN_FILES=()
for f in "${FILES[@]}"; do
  if [[ -f "$f" ]] && ! [[ "$f" =~ $EXCLUDE_REGEX ]]; then
    SCAN_FILES+=("$f")
  fi
done

if [[ "${#SCAN_FILES[@]}" -eq 0 ]]; then
  echo "secret_scan: no files to scan"
  exit 0
fi

# Secret-shaped patterns:
#   - Google API key: AIza followed by 35 alnum/_/- chars
#   - GitHub token: ghp_ followed by 36 alnum chars
#   - AWS access key id: AKIA followed by 16 uppercase alnum chars
#   - PEM private key header
#   - api_key=/apikey=/password=/secret= assigned to a non-placeholder-looking value
PATTERN='AIza[0-9A-Za-z_-]{35}|ghp_[0-9A-Za-z]{36}|AKIA[0-9A-Z]{16}|-----BEGIN (RSA |EC |OPENSSH |DSA |)PRIVATE KEY-----'

FOUND=0

if grep -EnH "$PATTERN" "${SCAN_FILES[@]}" 2>/dev/null; then
  FOUND=1
fi

# api_key=/password=/secret= with a real-looking (non-placeholder) value.
# Skip obvious placeholders like REPLACE_ME, YOUR_, <..>, xxx, ${...}, empty.
ASSIGN_PATTERN='(api[_-]?key|password|secret)[[:space:]]*[:=][[:space:]]*["'\''"]?[A-Za-z0-9_/+.-]{12,}'
PLACEHOLDER_PATTERN='REPLACE_ME|YOUR_|CHANGE_ME|PLACEHOLDER|xxxxxxxx|\$\{|<.*>|example'

while IFS=: read -r file line content; do
  [[ -z "${file:-}" ]] && continue
  if echo "$content" | grep -qiE "$PLACEHOLDER_PATTERN"; then
    continue
  fi
  echo "$file:$line:$content"
  FOUND=1
done < <(grep -EnHi "$ASSIGN_PATTERN" "${SCAN_FILES[@]}" 2>/dev/null || true)

if [[ "$FOUND" -ne 0 ]]; then
  echo "secret_scan: possible secret(s) detected above" >&2
  exit 1
fi

echo "secret_scan: no secrets detected"
exit 0
