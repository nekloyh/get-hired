#!/usr/bin/env bash
# Cut a release in two steps, so that a release never again needs a "docs catch up with the tag" PR
# (#140; PR #137 existed only to resync five files after v0.2.0).
#
#   scripts/release.sh prepare 0.3.0   on a branch: set the version in pyproject.toml, uv.lock and
#                                      web/package{,-lock}.json; turn `## [Unreleased]` into
#                                      `## [0.3.0] — <today>`; commit. Push, open a PR, merge it with
#                                      a MERGE COMMIT. Squash and rebase rewrite the sha.
#   scripts/release.sh tag 0.3.0       on main, after that merge: run the gate, tag, push the tag NOW.
#
# Why the tag is pushed in the same step: this machine has `fetch.pruneTags=true`, so the next
# `git fetch --all --tags` DELETES a local tag that was never pushed. That is how v0.1.0-pilot was lost
# once. Status itself is not edited here or anywhere else: CHANGELOG.md holds what shipped and GitHub
# holds the rest (docs/issues/README.md, "Where status lives").
set -euo pipefail
cd "$(dirname "$0")/.."

die() { echo "release: $*" >&2; exit 1; }
[ $# -eq 2 ] || { echo "usage: $0 prepare|tag <x.y.z[-suffix]>" >&2; exit 2; }
cmd=$1
ver=$2
[[ $ver =~ ^[0-9]+\.[0-9]+\.[0-9]+(-[0-9A-Za-z.]+)?$ ]] || die "not a version: $ver"

case "$cmd" in
  prepare)
    [ -z "$(git status --porcelain)" ] || die "working tree is not clean"
    [ "$(git rev-parse --abbrev-ref HEAD)" != main ] || die "prepare runs on a branch, not on main"
    git rev-parse -q --verify "refs/tags/v$ver" >/dev/null && die "tag v$ver already exists"
    prev=$(git describe --tags --abbrev=0 --match 'v[0-9]*' HEAD) || die "no earlier v* tag reachable from HEAD"

    # CHANGELOG first: it is the step that can refuse (empty or missing [Unreleased]).
    uv run --no-sync python - "$ver" "$(date -u +%F)" "$prev" <<'PY'
import re, sys
from pathlib import Path

ver, today, prev = sys.argv[1:4]
repo = "https://github.com/nekloyh/get-hired"
path = Path("CHANGELOG.md")
text = path.read_text(encoding="utf-8")
if f"## [{ver}]" in text:
    sys.exit(f"release: CHANGELOG.md already has a [{ver}] entry")
match = re.search(r"^## \[Unreleased\]\n(.*?)(?=^## \[)", text, flags=re.M | re.S)
if not match:
    sys.exit("release: CHANGELOG.md has no '## [Unreleased]' section followed by an earlier release")
body = re.sub(r"^\[#\d+\]: .*$|^---$", "", match.group(1), flags=re.M)
if not body.strip():
    sys.exit("release: '## [Unreleased]' is empty, so there is nothing to release")
text = text.replace("## [Unreleased]\n", f"## [Unreleased]\n\n---\n\n## [{ver}] — {today}\n", 1)
unreleased_ref = re.compile(r"^\[Unreleased\]: .*$", flags=re.M)
if not unreleased_ref.search(text):
    sys.exit("release: CHANGELOG.md has no '[Unreleased]: <compare link>' reference")
text = unreleased_ref.sub(
    f"[Unreleased]: {repo}/compare/v{ver}...HEAD\n[{ver}]: {repo}/compare/{prev}...v{ver}", text, count=1
)
path.write_text(text, encoding="utf-8")
PY

    sed -i -E "0,/^version = \"[^\"]*\"/s//version = \"$ver\"/" pyproject.toml
    grep -q "^version = \"$ver\"$" pyproject.toml || die "could not set the version in pyproject.toml"
    # uv.lock records the project's own version; CI's `uv sync --locked` fails if it is stale. Edit that
    # one line rather than run `uv lock`. A full re-lock took ~2 min, and a newer local uv rewrote the
    # file's format `revision` (3 -> 5) as a side effect. CI and the Docker image install whatever uv is
    # latest, so a release must not depend on which uv this machine happens to have.
    sed -i -E "/^name = \"interview-coach\"$/{n;s/^version = \"[^\"]*\"$/version = \"$ver\"/}" uv.lock
    grep -A1 '^name = "interview-coach"$' uv.lock | grep -q "^version = \"$ver\"$" || die "could not set the version in uv.lock"
    uv lock --check --quiet || die "uv.lock does not match pyproject.toml"
    (cd web && npm version "$ver" --no-git-tag-version --allow-same-version >/dev/null)

    git add CHANGELOG.md pyproject.toml uv.lock web/package.json web/package-lock.json
    git commit -q -m "chore: release $ver"
    echo "release: committed 'chore: release $ver' (previous tag $prev)."
    echo "Next: push, open a PR, merge it with a merge commit, then on main: $0 tag $ver"
    ;;

  tag)
    [ "$(git rev-parse --abbrev-ref HEAD)" = main ] || die "tag runs on main"
    [ -z "$(git status --porcelain)" ] || die "working tree is not clean"
    git fetch -q origin main
    [ "$(git rev-parse HEAD)" = "$(git rev-parse origin/main)" ] || die "local main is not origin/main; pull first"
    grep -q "^version = \"$ver\"$" pyproject.toml || die "pyproject.toml is not at $ver; merge the prepare PR first"
    grep -q "^## \[$ver\]" CHANGELOG.md || die "CHANGELOG.md has no [$ver] entry"
    git rev-parse -q --verify "refs/tags/v$ver" >/dev/null && die "tag v$ver already exists locally"
    git ls-remote --exit-code origin "refs/tags/v$ver" >/dev/null && die "tag v$ver already exists on origin"

    scripts/gate.sh || die "the gate is red; no tag"
    git tag -a "v$ver" -m "v$ver"
    git push -q origin "refs/tags/v$ver"
    git ls-remote --exit-code origin "refs/tags/v$ver" >/dev/null || die "pushed, but origin does not show v$ver"
    echo "release: v$ver is on origin at $(git rev-parse --short HEAD)."
    ;;

  *)
    echo "usage: $0 prepare|tag <x.y.z[-suffix]>" >&2
    exit 2
    ;;
esac
