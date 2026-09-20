#!/usr/bin/env bash
# Run a Playwright command and fail unless it actually RAN a test.
#
# `test.skip` exits 0. `demo-flow` skips when no backend answers; `reconnect-flow` skips on the wrong
# Playwright project, the wrong VITE_API_URL, or a backend that never came up. Four ways for this job
# to report green having executed nothing, which is worse than not having the job — so the JSON
# report is read and a skip is a failure.
#
#   e2e-ran.sh <label> <command...>     `--reporter=line,json` is appended to the command
#
# The report goes to a FILE via PLAYWRIGHT_JSON_OUTPUT_NAME rather than stdout: `npm run` prints its
# own `> pkg@version script` banner first, and that banner is not JSON.
set -uo pipefail
label="$1"; shift

report="$PWD/playwright-$label.json"
rm -f "$report"
PLAYWRIGHT_JSON_OUTPUT_NAME="$report" "$@" --reporter=line,json
status=$?

if [ ! -s "$report" ]; then
  echo "e2e[$label]: no JSON report was written (command exited $status)" >&2
  exit 1
fi

node -e '
  const fs = require("fs")
  const [label, file] = process.argv.slice(1)
  const stats = JSON.parse(fs.readFileSync(file, "utf8")).stats || {}
  const { expected = 0, unexpected = 0, skipped = 0, flaky = 0 } = stats
  console.log(`e2e[${label}]: ${JSON.stringify({ expected, unexpected, skipped, flaky })}`)
  if (unexpected > 0) { console.error(`e2e[${label}]: ${unexpected} test(s) failed`); process.exit(1) }
  if (skipped > 0) { console.error(`e2e[${label}]: ${skipped} test(s) SKIPPED — a skip is not a pass here`); process.exit(1) }
  if (expected < 1) { console.error(`e2e[${label}]: nothing ran`); process.exit(1) }
' "$label" "$report" || exit 1

exit $status
