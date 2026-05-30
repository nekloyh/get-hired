#!/usr/bin/env bash
# Create the 13 vertical-slice issues on GitHub from the drafts in docs/issues/.
#
# Run this in a terminal where `gh` is installed and authenticated:
#     bash scripts/create_issues.sh
#
# It is safe to read first. It refuses to run if the repo already has issues,
# so it won't create duplicates. Created in filename order on a fresh repo,
# slice 000N becomes GitHub issue #N — so a body that says "Blocked by: 0005"
# maps to issue #5.
set -euo pipefail
cd "$(dirname "$0")/.."

command -v gh >/dev/null || { echo "ERROR: gh not found on PATH. Install github-cli and 'gh auth login' first."; exit 1; }
gh auth status >/dev/null 2>&1 || { echo "ERROR: gh is not authenticated. Run: gh auth login"; exit 1; }

existing=$(gh issue list --state all --limit 1 --json number --jq 'length' 2>/dev/null || echo "0")
if [ "$existing" != "0" ]; then
  echo "ERROR: this repo already has issues. Aborting to avoid duplicates."
  echo "If you really want to proceed, delete the existing issues first or edit this script."
  exit 1
fi

for f in docs/issues/0*.md; do
  title=$(head -n1 "$f" | sed 's/^#[[:space:]]*//')
  echo ">> Creating issue for $(basename "$f"): $title"
  gh issue create --title "$title" --body-file "$f"
done

echo
echo "All issues created. Current list:"
gh issue list --state all --limit 20
