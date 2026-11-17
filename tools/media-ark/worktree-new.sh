#!/usr/bin/env bash
# worktree-new.sh — opinionated wrapper around `git worktree add` for media-ark.
#
# Enforces the standing-rules convention from conductor/fleet-standing-rules.md
# and conductor/routing.toml `intent.worktree-new`:
# - Worktree name format: media-ark--<purpose>
# - Default peer location: ~/Workspace/4444J99/media-ark--<purpose>
# - Cross-host Desktop peer (~/Desktop/media-ark--<purpose>): only when
#   the conductor has explicitly opted in via --desktop (the retirement
#   rule from PR #18 names this as the one exception)
# - Base branch: origin/main (default; override with --base)
# - Branch name: <prefix>/<purpose> where prefix is one of feat/, fix/,
#   docs/, chore/, ci/, evolve/ (Conventional Commits convention)
# - The new worktree is a *peer* of the main clone, not a nested subdir
#
# The wrapper does NOT take a destructive action. The standing rules
# forbid `git worktree remove` and `git branch -D` without conductor
# authorization (see conductor/fleet-standing-rules.md #5); the prune
# half of the workflow is a separate script (worktree-prune.sh, future).
set -euo pipefail

usage() {
  cat <<'EOF'
Usage:
  worktree-new.sh --purpose <slug> [--prefix <prefix>] [--base <branch>] [--desktop]

Required:
  --purpose <slug>     The purpose slug. Becomes part of the worktree name
                       (media-ark--<slug>) and the branch name
                       (<prefix>/<slug>).

Optional:
  --prefix <prefix>    Branch prefix. One of: feat, fix, docs, chore, ci, evolve.
                       Default: feat
  --base <branch>      Base branch to fork from. Default: origin/main
  --desktop            Place the worktree at ~/Desktop/media-ark--<slug>
                       (the cross-host peer convention; retired by default
                       per conductor/routing.toml `intent.worktree-peer-Desktop`,
                       re-enabled per-conductor-decision via this flag).
  --workspace-root <path>
                       Override the workspace root. Default: ~/Workspace/4444J99
  --dry-run            Print the commands that would be run, do not execute.
  -h, --help           Show this help.

Examples:
  worktree-new.sh --purpose pr-19-worktree
  worktree-new.sh --purpose pr-20-conductor-ci --prefix feat
  worktree-new.sh --purpose 2026-06-11-host-peer --desktop
  worktree-new.sh --purpose hotfix-typo --prefix fix --base origin/main

Exit codes:
  0  success (worktree created and branch pushed to origin, or dry-run completed)
  1  invalid arguments
  2  prerequisites missing (git, repo not found, not on the expected host)
  3  worktree name or branch name validation failed
  4  worktree already exists
  5  push failed
EOF
}

PURPOSE=""
PREFIX="feat"
BASE_BRANCH="origin/main"
DESKTOP_PEER=0
WORKSPACE_ROOT="${HOME}/Workspace/4444J99"
DRY_RUN=0

while [[ $# -gt 0 ]]; do
  case "$1" in
  --purpose)
    PURPOSE="$2"
    shift 2
    ;;
  --prefix)
    PREFIX="$2"
    shift 2
    ;;
  --base)
    BASE_BRANCH="$2"
    shift 2
    ;;
  --desktop)
    DESKTOP_PEER=1
    shift
    ;;
  --workspace-root)
    WORKSPACE_ROOT="$2"
    shift 2
    ;;
  --dry-run)
    DRY_RUN=1
    shift
    ;;
  -h | --help)
    usage
    exit 0
    ;;
  *)
    echo "Unknown argument: $1" >&2
    usage
    exit 1
    ;;
  esac
done

if [[ -z "$PURPOSE" ]]; then
  echo "--purpose is required" >&2
  usage
  exit 1
fi

# Validate purpose: kebab-case, no slashes, no double-hyphens (the worktree
# name format is `media-ark--<purpose>` and a third `--` would break
# downstream parsers that read the worktree name to extract the purpose).
if [[ ! "$PURPOSE" =~ ^[a-z0-9][a-z0-9-]*[a-z0-9]$ ]]; then
  echo "Invalid --purpose: '$PURPOSE'. Must be kebab-case (lowercase, digits, hyphens, no leading/trailing hyphen, no double-hyphen)." >&2
  exit 3
fi
if [[ "$PURPOSE" == *"--"* ]]; then
  echo "Invalid --purpose: '$PURPOSE' contains a double-hyphen. The worktree name format is media-ark--<purpose>; a third -- breaks the parser." >&2
  exit 3
fi

# Validate prefix
case "$PREFIX" in
feat | fix | docs | chore | ci | evolve) ;;
*)
  echo "Invalid --prefix: '$PREFIX'. Must be one of feat, fix, docs, chore, ci, evolve." >&2
  exit 3
  ;;
esac

# Validate base branch
if [[ ! "$BASE_BRANCH" =~ ^(origin|local)/[A-Za-z0-9._/-]+$ ]]; then
  echo "Invalid --base: '$BASE_BRANCH'. Must be in the form origin/<branch> or local/<branch>." >&2
  exit 3
fi

# Resolve worktree location
if [[ "$DESKTOP_PEER" == "1" ]]; then
  WORKTREE_PARENT="${HOME}/Desktop"
  PEER_KIND="Desktop (cross-host peer — requires conductor authorization per conductor/routing.toml)"
else
  WORKTREE_PARENT="${WORKSPACE_ROOT}"
  PEER_KIND="workspace (default)"
fi

WORKTREE_NAME="media-ark--${PURPOSE}"
WORKTREE_PATH="${WORKTREE_PARENT}/${WORKTREE_NAME}"
BRANCH_NAME="${PREFIX}/${PURPOSE}"

# Pre-flight checks
if ! command -v git >/dev/null 2>&1; then
  echo "git is required but not found in PATH" >&2
  exit 2
fi

if [[ ! -d "${WORKSPACE_ROOT}/media-ark" ]]; then
  echo "Main clone not found at ${WORKSPACE_ROOT}/media-ark. Set --workspace-root to override." >&2
  exit 2
fi

if [[ -d "$WORKTREE_PATH" ]]; then
  echo "Worktree path already exists: $WORKTREE_PATH" >&2
  echo "  (use 'git worktree list' to see existing worktrees, or pick a different --purpose)" >&2
  exit 4
fi

# Verify the base branch exists locally
REPO_ROOT="${WORKSPACE_ROOT}/media-ark"
if ! git -C "$REPO_ROOT" rev-parse --verify --quiet "$BASE_BRANCH" >/dev/null 2>&1; then
  echo "Base branch not found: $BASE_BRANCH. Fetch first: git -C $REPO_ROOT fetch origin" >&2
  exit 2
fi

# Print the plan
cat <<EOF
worktree-new.sh plan:
  purpose:     $PURPOSE
  branch:      $BRANCH_NAME
  base:        $BASE_BRANCH
  worktree:    $WORKTREE_PATH
  peer:        $PEER_KIND
  dry-run:     $DRY_RUN
EOF

if [[ "$DRY_RUN" == "1" ]]; then
  echo
  echo "[dry-run] Would run:"
  echo "  git -C \"$REPO_ROOT\" worktree add -b \"$BRANCH_NAME\" \"$WORKTREE_PATH\" \"$BASE_BRANCH\""
  exit 0
fi

# Execute
echo
echo "Creating worktree..."
git -C "$REPO_ROOT" worktree add -b "$BRANCH_NAME" "$WORKTREE_PATH" "$BASE_BRANCH"

echo
echo "Done. Worktree ready at: $WORKTREE_PATH"
echo "  cd \"$WORKTREE_PATH\""
echo "  # ... work, commit, push ..."
echo "  # when ready to merge: hand the conductor a ready-to-paste gh pr create command"
