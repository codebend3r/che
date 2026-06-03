#!/opt/homebrew/bin/bash

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
. "$SCRIPT_DIR/../utils.sh" --source-only

set -euo pipefail

# v3.0.0

info "Running command in $(pwd)"

# Usage:
#   delete-empty-folders --path=./ --dry-run=true

DRY_RUN="${DRY_RUN:-true}"   # Repo policy: destructive tools default preview-only unless wrapper sets env.
VERBOSE=false
ROOT_DIR=""
DELETED_COUNT=0

# ⚙️  CLI — long flags only (see ../utils.sh).
while [[ $# -gt 0 ]]; do
  case "$1" in
    --path=*) ROOT_DIR="${1#*=}"; shift ;;
    --dry-run=*) DRY_RUN="${1#*=}"; shift ;;
    --dry-run) DRY_RUN=true; shift ;;
    --verbose=*) VERBOSE="${1#*=}"; shift ;;
    --verbose) VERBOSE=true; shift ;;
    -h|--help)
      info "📋 Usage: $0 --path=/dir [--dry-run] [--verbose]"
      exit 0
      ;;
    *)
      warning "❌ Unknown argument: $1"
      warning "📋 Usage: $0 --path=/dir [--dry-run] [--verbose]"
      exit 1
      ;;
  esac
done

if [[ -z "$ROOT_DIR" ]]; then
  warning "Error: --path is required."
  exit 1
fi

if [[ ! -d "$ROOT_DIR" ]]; then
  warning "Error: Directory not found: $ROOT_DIR"
  exit 1
fi

note "Searching in: $ROOT_DIR"
note "Dry run: ${DRY_RUN}"
note "Verbose: ${VERBOSE}"

# Deepest-first traversal so that emptying a leaf can cascade up. Only
# truly-empty dirs are removed — a folder containing only .DS_Store / ._*
# / .git is intentionally left alone (rm -rf would silently wipe them).
while IFS= read -r -d '' dir; do
  # Don't ever touch the root the user pointed at.
  [[ "$dir" == "$ROOT_DIR" ]] && continue

  # Strict-empty check: any entry (including hidden) disqualifies.
  if [[ -n "$(ls -A "$dir" 2>/dev/null)" ]]; then
    $VERBOSE && note "Skipped (not empty): $dir"
    continue
  fi

  if $DRY_RUN; then
    log "[DRY-RUN] Would delete: $dir"
  else
    rmdir "$dir"
    log "Deleted: $dir"
  fi
  ((DELETED_COUNT++))
done < <(find "$ROOT_DIR" -depth -type d -print0)

log "📊 Total deleted directories: $DELETED_COUNT"
