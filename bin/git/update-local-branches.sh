#!/usr/bin/env bash

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
. "$SCRIPT_DIR/../utils.sh" --source-only

set -euo pipefail

# v3.0.0

usage() {
  cat <<EOF
Usage:
  $(basename "$0") [--limit=N] [--dry-run]

Description:
  ⬇️  For each local branch with an upstream, rebase onto origin.
  Conflicts are aborted and reported; the script keeps going.

Options:
  --limit=N    Only update the N most recently committed branches
  --dry-run    List branches that would be updated, change nothing
  --help       Show help
EOF
}

LIMIT=0
DRY_RUN=false

# ⚙️  CLI — long flags only; `--dry-run` or `--dry-run=true|false` (see ../utils.sh).
while [[ $# -gt 0 ]]; do
  case "$1" in
    --limit=*)
      LIMIT="${1#*=}"
      shift
      ;;
    --dry-run=*)
      DRY_RUN="${1#*=}"
      shift
      ;;
    --dry-run)
      DRY_RUN=true
      shift
      ;;
    --help|-h)
      usage
      exit 0
      ;;
    *)
      warning "❌ Unknown argument: $1"
      usage
      exit 1
      ;;
  esac
done

if ! [[ "$LIMIT" =~ ^[0-9]+$ ]]; then
  warning "❌ --limit must be a non-negative integer (got: $LIMIT)"
  exit 1
fi

header_suffix=""
[[ "$DRY_RUN" == true ]] && header_suffix=" 🌵 (dry run)"

note "═══════════════════════════════════════════"
note "⬇️   update-local-branches${header_suffix}"
note "═══════════════════════════════════════════"

ORIGINAL_BRANCH=$(git symbolic-ref --quiet --short HEAD 2>/dev/null || true)
if [[ -z "$ORIGINAL_BRANCH" ]]; then
  warning "❌ Detached HEAD — check out a branch first."
  exit 1
fi

if [[ "$DRY_RUN" != true && -n "$(git status --porcelain)" ]]; then
  warning "❌ Working tree is dirty. Commit or stash before running. 🧺"
  exit 1
fi

info "📡 Fetching remotes..."
git fetch --all --quiet

# Branches with an upstream, newest first.
branches=()
while IFS= read -r b; do
  [[ -n "$b" ]] && branches+=("$b")
done < <(
  git for-each-ref \
    --sort=-committerdate \
    --format='%(refname:short)|%(upstream)' \
    refs/heads/ \
  | awk -F'|' '$2 != "" { print $1 }'
)

if [[ "$LIMIT" -gt 0 && ${#branches[@]} -gt "$LIMIT" ]]; then
  branches=("${branches[@]:0:$LIMIT}")
fi

if [[ ${#branches[@]} -eq 0 ]]; then
  info "ℹ️  No local branches with upstreams."
  exit 0
fi

if [[ "$DRY_RUN" == true ]]; then
  info "🌵 Would update ${#branches[@]} branch(es):"
  for b in "${branches[@]}"; do
    info "  • 🌿 $b"
  done
  exit 0
fi

succeeded=()
failed=()

for branch in "${branches[@]}"; do
  info "📂 Switching to 🌿 $branch"
  if ! git checkout --quiet "$branch" 2>/dev/null; then
    warning "  ✗ checkout failed, skipping"
    failed+=("$branch")
    continue
  fi

  log "⬇️  Rebasing $branch onto upstream"
  if git pull --rebase --quiet; then
    success "  ✅ $branch up to date"
    succeeded+=("$branch")
  else
    warning "  ❌ rebase failed — aborting and moving on"
    git rebase --abort 2>/dev/null || true
    failed+=("$branch")
  fi
done

info "🔁 Returning to 🌿 $ORIGINAL_BRANCH"
git checkout --quiet "$ORIGINAL_BRANCH"

echo
success "═══ summary ═══"
success "✅ Updated: ${#succeeded[@]}"
if [[ ${#failed[@]} -gt 0 ]]; then
  warning "❌ Failed:  ${#failed[@]}"
  for b in "${failed[@]}"; do
    warning "  • 💥 $b"
  done
  exit 1
fi
success "🎉 All clean!"
