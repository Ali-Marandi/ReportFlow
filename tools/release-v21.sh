#!/usr/bin/env bash
# ReportFlow v2.1 release automation.
# Default mode validates the candidate only. --publish makes public GitHub changes
# and is intentionally gated by REPORTFLOW_RELEASE_CONFIRM=YES.
set -euo pipefail

VERSION="v2.1.0"
SOURCE_BRANCH="feature/v2-enterprise-foundations"
PUBLISH=0

usage() {
  cat <<'EOF'
Usage: tools/release-v21.sh [--version v2.1.0] [--source feature/v2-enterprise-foundations] [--publish]

Without --publish this command runs the complete local release gate and prints
what would be merged/tagged. With --publish it fast-forwards main, creates an
annotated tag, pushes both, and starts the protected GitHub signing workflow.

Required only with --publish:
  REPORTFLOW_RELEASE_CONFIRM=YES
  gh authenticated with repository write permission
EOF
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --version) VERSION="$2"; shift 2 ;;
    --source) SOURCE_BRANCH="$2"; shift 2 ;;
    --publish) PUBLISH=1; shift ;;
    -h|--help) usage; exit 0 ;;
    *) echo "Unknown option: $1" >&2; usage >&2; exit 2 ;;
  esac
done

[[ "$VERSION" =~ ^v2\.1\.[0-9]+$ ]] || { echo "Version must use v2.1.x semantic versioning." >&2; exit 2; }
ROOT="$(git rev-parse --show-toplevel)"
[[ -z "$(git status --porcelain)" ]] || { echo "Working tree is not clean." >&2; exit 1; }
git show-ref --verify --quiet "refs/heads/$SOURCE_BRANCH" || { echo "Source branch does not exist: $SOURCE_BRANCH" >&2; exit 1; }
! git rev-parse -q --verify "refs/tags/$VERSION" >/dev/null || { echo "Tag already exists: $VERSION" >&2; exit 1; }

VALIDATION_DIR="$ROOT"
TEMP_WORKTREE=""
if [[ "$(git branch --show-current)" != "$SOURCE_BRANCH" ]]; then
  TEMP_WORKTREE="$(mktemp -d)"
  git worktree add --detach "$TEMP_WORKTREE" "$SOURCE_BRANCH" >/dev/null
  VALIDATION_DIR="$TEMP_WORKTREE"
  trap '[[ -n "${TEMP_WORKTREE:-}" ]] && git -C "$ROOT" worktree remove --force "$TEMP_WORKTREE"' EXIT
fi

echo "==> Local validation for $VERSION from $SOURCE_BRANCH"
cd "$VALIDATION_DIR"
QT_QPA_PLATFORM=offscreen pytest -q
python3 -m compileall -q reportflow_app
pip-audit -r requirements.txt
bandit -r reportflow_app -q

echo "==> Candidate commits"
git -C "$ROOT" log --oneline "main..$SOURCE_BRANCH"
echo "==> Intended public changes"
echo "  main: fast-forward to $SOURCE_BRANCH"
echo "  tag:  $VERSION"
echo "  workflow: Build, sign, and publish ReportFlow for Windows"
cd "$ROOT"

if [[ "$PUBLISH" -eq 0 ]]; then
  echo "==> Dry-run completed. No branch, tag, Release, asset, or remote state was changed."
  exit 0
fi

[[ "${REPORTFLOW_RELEASE_CONFIRM:-}" == "YES" ]] || {
  echo "Refusing public release. Set REPORTFLOW_RELEASE_CONFIRM=YES only after authorized release approval." >&2
  exit 3
}
command -v gh >/dev/null || { echo "GitHub CLI is required for publishing." >&2; exit 1; }
gh auth status >/dev/null

git fetch origin --tags --prune
! git rev-parse -q --verify "refs/tags/$VERSION" >/dev/null || { echo "Tag already exists after remote fetch: $VERSION" >&2; exit 1; }
git checkout main
git pull --ff-only origin main
git merge --ff-only "$SOURCE_BRANCH"
git tag -a "$VERSION" -m "ReportFlow $VERSION"
git push origin main "$VERSION"

echo "==> Public branch and tag were pushed. GitHub Actions now runs the protected signing job."
echo "==> The Release is created only after the production-release environment approval and Authenticode verification succeed."
echo "==> Monitor: gh run list --workflow windows-build.yml --branch main --limit 5"
