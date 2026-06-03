#!/usr/bin/env bash

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=bin/utils.sh
. "$SCRIPT_DIR/../utils.sh" --source-only

set -euo pipefail

# v3.0.0

DEFAULT_PROTECTED=(main master dev develop staging)

usage() {
  cat <<EOF
Usage:
  $(basename "$0") [--dry-run] [--protect=BRANCH1,BRANCH2,...]

Description:
  🧹 Delete local branches whose upstream is gone (the remote branch was
  deleted). Protected branches and the current branch are never deleted.

Options:
  --dry-run        Show what would be deleted, change nothing
  --protect=LIST   Comma-separated extra branches to protect
                   (defaults: ${DEFAULT_PROTECTED[*]})
  --help           Show help

Env:
  DRY_RUN=true     Same as --dry-run (used by the .zshrc -dr wrapper)
EOF
}

DRY_RUN="${DRY_RUN:-false}"
EXTRA_PROTECTED=()

# ⚙️  CLI — long flags only; `--dry-run` or `--dry-run=true|false` (see ../utils.sh).
while [[ $# -gt 0 ]]; do
  case "$1" in
    --dry-run=*)
      DRY_RUN="${1#*=}"
      shift
      ;;
    --dry-run)
      DRY_RUN=true
      shift
      ;;
    --protect=*)
      IFS=',' read -r -a EXTRA_PROTECTED <<< "${1#*=}"
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

PROTECTED=("${DEFAULT_PROTECTED[@]}" ${EXTRA_PROTECTED[@]+"${EXTRA_PROTECTED[@]}"})
CURRENT_BRANCH=$(git symbolic-ref --quiet --short HEAD 2>/dev/null || true)

is_protected() {
  local b=$1 p
  for p in "${PROTECTED[@]}"; do
    [[ "$b" == "$p" ]] && return 0
  done
  return 1
}

header_suffix=""
[[ "$DRY_RUN" == true ]] && header_suffix=" 🌵 (dry run)"

note "═══════════════════════════════════════════"
note "🧹  clean-stale-branches${header_suffix}"
note "═══════════════════════════════════════════"

info "📡 Fetching + pruning remotes..."
git fetch --all --prune --quiet

info "🔍 Scanning local branches for gone upstreams..."

stale=()
while IFS='|' read -r branch track; do
  [[ -z "$branch" ]] && continue
  if is_protected "$branch"; then
    continue
  fi
  if [[ "$branch" == "$CURRENT_BRANCH" ]]; then
    note "⏭️  Skipping current branch: $branch"
    continue
  fi
  if [[ "$track" == *"[gone]"* ]]; then
    stale+=("$branch")
  fi
done < <(git for-each-ref --format='%(refname:short)|%(upstream:track)' refs/heads/)

if [[ ${#stale[@]} -eq 0 ]]; then
  success "✨ No stale branches. All clean! 🎉"
  exit 0
fi

if [[ "$DRY_RUN" == true ]]; then
  warning "🌵 ${#stale[@]} stale branch(es) would be deleted:"
  for b in "${stale[@]}"; do
    warning "  • 🪦 $b"
  done
  log "💡 Dry run complete. Nothing was actually deleted."
else
  for b in "${stale[@]}"; do
    warning "🗑️  Deleting: $b"
    git branch -D "$b"
  done
  success "✨ Removed ${#stale[@]} stale branch(es). 🎉"
fi
