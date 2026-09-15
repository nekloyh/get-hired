#!/usr/bin/env bash
# The local stable gate: every check CI runs, in one command, with one verdict per line.
#
# Why a script and not a README list: the failure this keeps happening is reading three verdict
# lines and acting on two of them. `uv run mypy` prints its result on the LAST line, `pytest -q`
# prints a summary that is easy to `tail` past, and a `&&` chain stops at the first failure so you
# never learn whether the other two would also have failed. Every check below runs, every check
# reports, and the exit code is the AND of all of them.
#
#   scripts/gate.sh              python + web (what CI's `python` and `web` jobs run)
#   scripts/gate.sh --docker     also build the image and validate the compose file
#   scripts/gate.sh --e2e        also run the two Playwright specs (needs a backend on :8000)
#   scripts/gate.sh --all        everything
set -uo pipefail
cd "$(dirname "$0")/.."

WITH_DOCKER=0
WITH_E2E=0
for arg in "$@"; do
  case "$arg" in
    --docker) WITH_DOCKER=1 ;;
    --e2e) WITH_E2E=1 ;;
    --all) WITH_DOCKER=1; WITH_E2E=1 ;;
    *) echo "unknown flag: $arg" >&2; exit 2 ;;
  esac
done

FAILED=()
run() {  # run <label> <command...>
  local label="$1"; shift
  printf '\n=== %s ===\n' "$label"
  if "$@"; then
    printf '  PASS  %s\n' "$label"
  else
    printf '  FAIL  %s\n' "$label"
    FAILED+=("$label")
  fi
}

run "ruff check"        uv run --no-sync ruff check
run "ruff format"       uv run --no-sync ruff format --check .
run "mypy"              uv run --no-sync mypy
run "pytest"            uv run --no-sync pytest -q

run "npm lint"          npm --prefix web run lint
run "npm test"          npm --prefix web test
run "npm build"         npm --prefix web run build

if [ "$WITH_DOCKER" = 1 ]; then
  # `docker compose config` needs a .env because the compose file declares one per service; this is
  # the same bootstrap docs/deploy.md gives the operator, not a test fixture.
  [ -f .env ] || cp .env.example .env
  run "compose config"  docker compose config -q
  run "docker build"    docker build -q .
fi

if [ "$WITH_E2E" = 1 ]; then
  # demo-flow SKIPS (and so reports green) when no backend answers on :8000. Prove one does first.
  run "backend on :8000" curl -sf -o /dev/null http://127.0.0.1:8000/api/health
  run "e2e demo"        bash -c 'cd web && npx playwright test e2e/demo-flow.spec.ts --project=chromium --reporter=line'
  run "e2e reconnect"   npm --prefix web run test:e2e:reconnect
fi

printf '\n'
if [ ${#FAILED[@]} -eq 0 ]; then
  echo "GATE: OK"
  exit 0
fi
printf 'GATE: FAILED (%d) -> %s\n' "${#FAILED[@]}" "${FAILED[*]}"
exit 1
