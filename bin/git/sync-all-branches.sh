#!/usr/bin/env bash

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=bin/utils.sh
. "$SCRIPT_DIR/../utils.sh" --source-only

set -euo pipefail

# v1.0.0

usage() {
  cat <<EOF
Usage:
  $(basename "$0") [--dry-run] [--no-push] [--keep-locked] [--author=EMAIL] [--limit=N]

Description:
  🔄 Sync everything: push every worktree to origin, collapse the pushed ones
     back into ordinary local branches, then run the usual branch hygiene.

  A worktree is a temporary workspace. Once its commits are on origin, the
  directory holds nothing the remote does not, so it is removed and the branch
  stays behind as a plain local branch that the later steps can update
  normally. That also clears the "already used by worktree" pin, which is what
  otherwise makes main un-checkoutable and stale branches un-deletable.

  Steps, in order:
    1. git fetch --all --prune
    2. Push every linked worktree's branch to origin
    3. Remove each pushed + clean worktree, keeping its branch
    4. Prune stale worktree admin records
    5. Switch the main clone to the main branch
    6. clean-stale-branches   (delete branches whose upstream is gone)
    7. update-local-branches  (rebase every branch onto its upstream)
    8. checkout-my-branches   (check out your remote branches that aren't local)

  A worktree is only collapsed when it is clean AND fully pushed. Anything
  else is kept and reported with the reason.

Options:
  --dry-run        Report what would be pushed / removed / synced, change nothing
  --no-push        Never push; only collapse worktrees that are already pushed
  --keep-locked    Leave locked worktrees alone (default: release the lock once
                   the worktree is pushed and clean)
  --author=EMAIL   Passed through to checkout-my-branches
  --limit=N        Passed through to checkout-my-branches
  --help           Show help

Env:
  DRY_RUN=true     Same as --dry-run (used by the .zshrc -dr wrapper)
EOF
}

DRY_RUN="${DRY_RUN:-false}"
PUSH=true
KEEP_LOCKED=false
AUTHOR=""
LIMIT=""

# ⚙️  CLI — long flags only; booleans via `--flag` or `--flag=true|false` (see ../utils.sh).
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
    --no-push)
      PUSH=false
      shift
      ;;
    --keep-locked)
      KEEP_LOCKED=true
      shift
      ;;
    --author=*)
      AUTHOR="${1#*=}"
      shift
      ;;
    --limit=*)
      LIMIT="${1#*=}"
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
note "🔄  sync-all-branches${header_suffix}"
note "═══════════════════════════════════════════"

# The main worktree is the first entry from `git worktree list --porcelain`.
# Every later step runs from there: a worktree cannot be removed while we are
# standing inside it, and the delegated scripts expect the main clone.
MAIN_WT="$(git worktree list --porcelain | awk '/^worktree /{print substr($0, 10); exit}')"
if [[ -z "$MAIN_WT" ]]; then
  warning "❌ Could not determine main worktree."
  exit 1
fi

STARTED_IN="$(pwd -P)"
cd "$MAIN_WT"

MAIN_BRANCH=""
for candidate in main master; do
  if git show-ref --verify --quiet "refs/heads/$candidate"; then
    MAIN_BRANCH="$candidate"
    break
  fi
done

if [[ -z "$MAIN_BRANCH" ]]; then
  warning "❌ Neither 'main' nor 'master' exists locally — refusing to sync."
  exit 1
fi

# -----------------------------------------------------------------------------
# Step 1 — fetch + prune
# -----------------------------------------------------------------------------

info "📡 Fetching + pruning remotes..."
if [[ "$DRY_RUN" == true ]]; then
  info "🌵 Would run: git fetch --all --prune"
else
  git fetch --all --prune --quiet
fi

# -----------------------------------------------------------------------------
# Steps 2-3 — push every worktree, then collapse the pushed ones
# -----------------------------------------------------------------------------

pushed=()
collapsed=()
kept=()

info "🌿 Inspecting linked worktrees..."

# Snapshot the map first: removing a worktree mutates the list we are walking.
worktrees=()
while IFS=$'\t' read -r wt_branch wt_path; do
  [[ -z "$wt_path" ]] && continue
  [[ "$wt_path" == "$MAIN_WT" ]] && continue
  worktrees+=("${wt_branch}"$'\t'"${wt_path}")
done < <(worktree_branch_map)

if [[ ${#worktrees[@]} -eq 0 ]]; then
  info "  ℹ️  No linked worktrees with a branch checked out."
fi

for entry in ${worktrees[@]+"${worktrees[@]}"}; do
  IFS=$'\t' read -r branch path <<< "$entry"

  # A dirty worktree holds work that only exists there. Never touch it.
  if ! worktree_is_clean "$path"; then
    kept+=("${branch} (${path}) — dirty")
    warning "  ⏭️  ${branch} — dirty, keeping ${path}"
    continue
  fi

  # Push whatever is not on origin yet, so the directory becomes redundant.
  if ! branch_is_pushed "$branch"; then
    if [[ "$PUSH" != true ]]; then
      kept+=("${branch} (${path}) — unpushed, --no-push")
      warning "  ⏭️  ${branch} — unpushed and --no-push, keeping ${path}"
      continue
    fi

    if [[ "$DRY_RUN" == true ]]; then
      info "  🌵 Would push: ${branch} → origin"
      pushed+=("$branch")
    else
      log "  ⬆️  Pushing ${branch} → origin"
      if git -C "$path" push --quiet --set-upstream origin "$branch"; then
        pushed+=("$branch")
      else
        kept+=("${branch} (${path}) — push failed")
        warning "  ❌ push failed for ${branch}, keeping ${path}"
        continue
      fi
    fi
  fi

  # Re-check rather than assume: a push can succeed and still leave the branch
  # behind its upstream if someone else pushed in between.
  if [[ "$DRY_RUN" != true ]] && ! branch_is_pushed "$branch"; then
    kept+=("${branch} (${path}) — still not fully pushed")
    warning "  ⏭️  ${branch} — still not fully pushed, keeping ${path}"
    continue
  fi

  if [[ "$DRY_RUN" == true ]]; then
    info "  🌵 Would collapse: ${path} (branch ${branch} kept)"
    collapsed+=("${branch} (${path})")
    continue
  fi

  # A lock is metadata stamped by whatever created the worktree (a tool, an
  # agent, the user), and `git worktree remove` refuses while one is set. The
  # lock says nothing about unsaved work — the clean and pushed gates above are
  # what protect that — so release it rather than skipping. This is NOT
  # --force, which is the flag that discards real work.
  if [[ "$KEEP_LOCKED" != true ]]; then
    git worktree unlock "$path" >/dev/null 2>&1 || true
  fi

  if git worktree remove "$path"; then
    success "  ✅ Collapsed ${path} — branch ${branch} kept"
    collapsed+=("${branch} (${path})")
  else
    kept+=("${branch} (${path}) — removal failed (locked?)")
    warning "  ❌ Could not remove ${path}"
  fi
done

# -----------------------------------------------------------------------------
# Step 4 — prune stale admin records
# -----------------------------------------------------------------------------

if [[ "$DRY_RUN" == true ]]; then
  info "🌵 Would run: git worktree prune"
else
  git worktree prune
fi

# -----------------------------------------------------------------------------
# Step 5 — park on main before anything tries to delete or rebase branches
# -----------------------------------------------------------------------------

CURRENT_BRANCH="$(git symbolic-ref --quiet --short HEAD 2>/dev/null || true)"

if [[ "$CURRENT_BRANCH" != "$MAIN_BRANCH" ]]; then
  if [[ -n "$(git status --porcelain --untracked-files=no)" ]]; then
    warning "❌ Main worktree has uncommitted changes — commit or stash first. 🧺"
    exit 1
  fi

  if [[ "$DRY_RUN" == true ]]; then
    info "🌵 Would switch to 🌿 ${MAIN_BRANCH} (currently on ${CURRENT_BRANCH:-detached})"
  else
    info "🔀 Switching to 🌿 ${MAIN_BRANCH} (from ${CURRENT_BRANCH:-detached})"
    git checkout --quiet "$MAIN_BRANCH"
  fi
else
  info "📍 Already on 🌿 ${MAIN_BRANCH}"
fi

# -----------------------------------------------------------------------------
# Steps 6-8 — delegate to the single-purpose scripts
# -----------------------------------------------------------------------------

delegate_args=()
[[ "$DRY_RUN" == true ]] && delegate_args+=(--dry-run)

echo
DRY_RUN="$DRY_RUN" bash "$SCRIPT_DIR/clean-stale-branches.sh" ${delegate_args[@]+"${delegate_args[@]}"}

echo
bash "$SCRIPT_DIR/update-local-branches.sh" ${delegate_args[@]+"${delegate_args[@]}"}

checkout_args=()
[[ -n "$AUTHOR" ]] && checkout_args+=("--author=$AUTHOR")
[[ -n "$LIMIT" ]] && checkout_args+=("--limit=$LIMIT")

if [[ "$DRY_RUN" == true ]]; then
  echo
  info "🌵 Would run: checkout-my-branches ${checkout_args[*]-}"
else
  echo
  bash "$SCRIPT_DIR/checkout-my-branches.sh" ${checkout_args[@]+"${checkout_args[@]}"}
fi

# -----------------------------------------------------------------------------
# Summary
# -----------------------------------------------------------------------------

echo
note "─────────────────────────────────────────────"
success "═══ worktree summary ═══"
success "⬆️  Pushed:    ${#pushed[@]}"
for b in ${pushed[@]+"${pushed[@]}"}; do
  success "  • 🌿 $b"
done
success "📦 Collapsed: ${#collapsed[@]}"
for b in ${collapsed[@]+"${collapsed[@]}"}; do
  success "  • 🪦 $b"
done
if [[ ${#kept[@]} -gt 0 ]]; then
  warning "⏭️  Kept:      ${#kept[@]}"
  for b in "${kept[@]}"; do
    warning "  • 🌿 $b"
  done
fi

if [[ "$STARTED_IN" != "$MAIN_WT" ]]; then
  info "📍 Started in ${STARTED_IN}; finished in ${MAIN_WT}."
  if [[ ! -d "$STARTED_IN" ]]; then
    warning "⚠️  ${STARTED_IN} was collapsed — your shell is in a stale directory."
    warning "   Run: cd ${MAIN_WT}"
  fi
fi

log "🎉 Sync complete."
