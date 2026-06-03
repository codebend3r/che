#!/usr/bin/env bash

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=bin/utils.sh
. "$SCRIPT_DIR/../utils.sh" --source-only

set -euo pipefail

# v1.1.0

usage() {
  cat <<EOF
Usage:
  $(basename "$0") [--dry-run] [--force]

Description:
  🌿 Remove every linked worktree in the current repository, then run
  'git worktree prune' to clear stale admin records. The main worktree
  (the one containing .git) is always left untouched.

Options:
  --dry-run    Show what would be removed, change nothing
  --force      Pass --force to 'git worktree remove' (drops dirty trees)
  --help       Show help

Env:
  DRY_RUN=true Same as --dry-run (used by the .zshrc -dr wrapper)
EOF
}

DRY_RUN="${DRY_RUN:-true}"
FORCE=false

# ⚙️  CLI — long flags only; `--force`/`--dry-run` accept optional `=value` (see ../utils.sh).
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
    --force=*)
      FORCE="${1#*=}"
      shift
      ;;
    --force)
      FORCE=true
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

if ! git rev-parse --is-inside-work-tree >/dev/null 2>&1; then
  warning "❌ Not inside a git working tree."
  exit 1
fi

header_suffix=""
[[ "$DRY_RUN" == true ]] && header_suffix=" 🌵 (dry run)"

note "═══════════════════════════════════════════"
note "🌿  prune-worktrees${header_suffix}"
note "═══════════════════════════════════════════"

# Move into the main worktree and switch to the main branch first. Removing a
# worktree fails if we're standing inside it, and starting from a known-good
# branch keeps the operation predictable.
MAIN_WT="$(git worktree list --porcelain | awk '/^worktree /{print $2; exit}')"
if [[ -z "$MAIN_WT" ]]; then
  warning "❌ Could not determine main worktree."
  exit 1
fi
cd "$MAIN_WT"

MAIN_BRANCH=""
for candidate in main master; do
  if git show-ref --verify --quiet "refs/heads/$candidate"; then
    MAIN_BRANCH="$candidate"
    break
  fi
done

if [[ -z "$MAIN_BRANCH" ]]; then
  warning "❌ Neither 'main' nor 'master' exists locally — refusing to prune."
  exit 1
fi

CURRENT_BRANCH="$(git symbolic-ref --quiet --short HEAD 2>/dev/null || true)"
if [[ "$CURRENT_BRANCH" != "$MAIN_BRANCH" ]]; then
  # Only block on tracked-file changes — untracked files (incl. linked
  # worktrees nested under the main worktree) won't be touched by checkout.
  if [[ -n "$(git status --porcelain --untracked-files=no)" ]]; then
    warning "❌ Main worktree has uncommitted changes — commit or stash before pruning. 🧺"
    exit 1
  fi
  if [[ "$DRY_RUN" == true ]]; then
    info "🌵 Would switch main worktree to 🌿 $MAIN_BRANCH (currently on ${CURRENT_BRANCH:-detached})"
  else
    info "🔀 Switching main worktree to 🌿 $MAIN_BRANCH (from ${CURRENT_BRANCH:-detached})"
    git checkout --quiet "$MAIN_BRANCH"
  fi
else
  info "📍 Main worktree already on 🌿 $MAIN_BRANCH"
fi

info "🔍 Listing worktrees..."

linked_paths=()
current_path=""
is_main=true

while IFS= read -r line; do
  if [[ "$line" == worktree\ * ]]; then
    if [[ -n "$current_path" && "$is_main" == false ]]; then
      linked_paths+=("$current_path")
    fi
    current_path="${line#worktree }"
    is_main=false
  elif [[ "$line" == "bare" ]]; then
    is_main=true
  elif [[ "$line" == "main" || "$line" == "main "* ]]; then
    is_main=true
  fi
done < <(git worktree list --porcelain)

# Tail entry
if [[ -n "$current_path" && "$is_main" == false ]]; then
  linked_paths+=("$current_path")
fi

# `git worktree list --porcelain` does not emit a "main" tag, so the first
# entry is the main worktree. Drop it from our removal list if it slipped in.
filtered=()
for p in ${linked_paths[@]+"${linked_paths[@]}"}; do
  [[ "$p" == "$MAIN_WT" ]] && continue
  filtered+=("$p")
done
linked_paths=(${filtered[@]+"${filtered[@]}"})

if [[ ${#linked_paths[@]} -eq 0 ]]; then
  success "✨ No linked worktrees. Running prune anyway... 🎉"
  if [[ "$DRY_RUN" == true ]]; then
    git worktree prune --dry-run --verbose || true
    log "💡 Dry run complete. Nothing was actually pruned."
  else
    git worktree prune --verbose
    success "✨ Pruned stale worktree records. 🎉"
  fi
  exit 0
fi

remove_args=()
[[ "$FORCE" == true ]] && remove_args+=(--force)

if [[ "$DRY_RUN" == true ]]; then
  warning "🌵 ${#linked_paths[@]} worktree(s) would be removed:"
  for p in "${linked_paths[@]}"; do
    warning "  • 🪦 $p"
  done
  info "📜 Would also run: git worktree prune --verbose"
  log "💡 Dry run complete. Nothing was actually removed."
else
  for p in "${linked_paths[@]}"; do
    warning "🗑️  Removing: $p"
    git worktree remove ${remove_args[@]+"${remove_args[@]}"} "$p"
  done
  info "🧹 Pruning stale worktree records..."
  git worktree prune --verbose
  success "✨ Removed ${#linked_paths[@]} worktree(s). 🎉"
fi
