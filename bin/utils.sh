#!/usr/bin/env bash

# =============================================================================
# 📋 CLI conventions — shared patterns for bin/<category>/*.sh
#
# • Long flags only: `--name=value` for values (no space-separated `-o val`
#   style in these scripts unless a specific tool documents otherwise).
# • Booleans: a bare `--flag` usually enables; many scripts also honor
#   `--flag=true|false` (sometimes yes|no, 1|0).
# • Help: `-h` / `--help` runs that script's usage() when one exists.
# • Parsing style: prefer `while [[ $# -gt 0 ]]` … `shift` so every script
#   handles argv the same way and new paired forms stay easy to add.
# =============================================================================

# Color definitions
NC='\033[0m'       # No Color
RED='\033[1;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
CYAN='\033[1;36m'
MAGENTA='\033[1;35m'

# Generic color logger
# log_color() {
#   local COLOR=$1
#   local MESSAGE=$2
#   printf '%b %s %b\n' "$COLOR" "$MESSAGE" "$NC"
# }

log_color() {
  local COLOR=$1
  local MESSAGE=$2
  printf '%b%b%b\n' "$COLOR" "$MESSAGE" "$NC"
}

# Specific log functions
log() {
  log_color "$GREEN" "$1"
}

warning() {
  log_color "$RED" "$1"
}

info() {
  log_color "$CYAN" "$1"
}

note() {
  log_color "$YELLOW" "$1"
}

success() {
  log_color "$MAGENTA" "$1"
}

###################
# Video functions

# Helper: formats bytes to PB, TB, GB, MB, KB, or bytes with 2 decimal places
format_bytes() {
  local bytes=$1

  local KB=1024
  local MB=$((KB * 1024))
  local GB=$((MB * 1024))
  local TB=$((GB * 1024))
  local PB=$((TB * 1024))

  if [[ $bytes -ge $PB ]]; then
    local val
    val=$(echo "scale=2; $bytes / $PB" | bc)
    echo "${val} PB"
  elif [[ $bytes -ge $TB ]]; then
    local val
    val=$(echo "scale=2; $bytes / $TB" | bc)
    echo "${val} TB"
  elif [[ $bytes -ge $GB ]]; then
    local val
    val=$(echo "scale=2; $bytes / $GB" | bc)
    echo "${val} GB"
  elif [[ $bytes -ge $MB ]]; then
    local val
    val=$(echo "scale=2; $bytes / $MB" | bc)
    echo "${val} MB"
  elif [[ $bytes -ge $KB ]]; then
    local val
    val=$(echo "scale=2; $bytes / $KB" | bc)
    echo "${val} KB"
  else
    echo "${bytes} B"
  fi
}

###################
# Worktree helpers
#
# A branch checked out in a linked worktree cannot be checked out, deleted or
# reset from the main clone — git refuses with "already used by worktree".
# That is a mechanical limit, not a conflict, so every script that touches
# branches needs to know which ones are pinned and where.

# Emit "<branch><TAB><path>" for every worktree that has a branch checked out.
# Detached worktrees are skipped (they pin no branch). The main worktree is
# included, because its branch is pinned for the same reason.
worktree_branch_map() {
  local path="" branch=""

  while IFS= read -r line; do
    case "$line" in
      "worktree "*)
        # A new record starts; flush the previous one.
        [[ -n "$path" && -n "$branch" ]] && printf '%s\t%s\n' "$branch" "$path"
        path="${line#worktree }"
        branch=""
        ;;
      "branch refs/heads/"*)
        branch="${line#branch refs/heads/}"
        ;;
    esac
  done < <(git worktree list --porcelain)

  [[ -n "$path" && -n "$branch" ]] && printf '%s\t%s\n' "$branch" "$path"
  return 0
}

# Print the worktree path holding BRANCH, or nothing when no worktree does.
worktree_for_branch() {
  local wanted=$1 branch path

  while IFS=$'\t' read -r branch path; do
    if [[ "$branch" == "$wanted" ]]; then
      printf '%s' "$path"
      return 0
    fi
  done < <(worktree_branch_map)

  return 1
}

# True when the worktree at PATH has no modified or untracked files.
# Ignored build output (node_modules, .next) does not count as dirty.
worktree_is_clean() {
  local path=$1
  [[ -z "$(git -C "$path" status --porcelain 2>/dev/null)" ]]
}

# True when every commit on BRANCH is already on its remote. Prefers the
# configured upstream and falls back to origin/<branch>.
branch_is_pushed() {
  local branch=$1 upstream

  upstream="$(git rev-parse --abbrev-ref --symbolic-full-name "${branch}@{upstream}" 2>/dev/null || true)"
  if [[ -z "$upstream" ]]; then
    upstream="origin/${branch}"
  fi

  git rev-parse --verify --quiet "$upstream" >/dev/null 2>&1 || return 1
  git merge-base --is-ancestor "$branch" "$upstream"
}
