#!/usr/bin/env bash

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=bin/utils.sh
. "$SCRIPT_DIR/../utils.sh" --source-only

set -euo pipefail

# v2.2.0

info "Running command in $(pwd)"

# Usage:
#   delete-by-ext --path=./ --ext=m3u,nfo,sfv,jpg,png,txt,log,cue,srr [--dry-run] [--verbose]

DRY_RUN="${DRY_RUN:-true}"   # Repo policy: destructive tools default preview-only unless wrapper sets env.
VERBOSE=false
ROOT_PATH=""
EXT_LIST=(m3u nfo sfv jpg png txt log cue srr)

# ⚙️  CLI — long flags only; booleans via `--flag` or `--flag=true|false` (see ../utils.sh).
while [[ $# -gt 0 ]]; do
  case "$1" in
    --path=*)
      ROOT_PATH="${1#*=}"
      shift
      ;;
    --ext=*)
      IFS=',' read -r -a EXT_LIST <<< "${1#*=}"
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
    --verbose=*)
      VERBOSE="${1#*=}"
      shift
      ;;
    --verbose)
      VERBOSE=true
      shift
      ;;
    -h|--help)
      info "📋 Usage: delete-by-ext --path=/dir --ext=jpg,png,mp4 […] [--dry-run] [--verbose]"
      exit 0
      ;;
    *)
      warning "❌ Unknown argument: $1"
      warning "📋 Usage: delete-by-ext --path=/dir --ext=jpg,png […] [--dry-run] [--verbose]"
      exit 1
      ;;
  esac
done

note "Scanning: $ROOT_PATH"
note "Extensions: ${EXT_LIST[*]}"
note "Dry run: $DRY_RUN"
note "Verbose: $VERBOSE"
note "----------------------------------------------------"

if [[ -z "$ROOT_PATH" ]]; then
  warning "--path is required"
  exit 1
fi

if [[ ${#EXT_LIST[@]} -eq 0 ]]; then
  warning "--ext is required"
  exit 1
fi

FIND_CMD=(find "$ROOT_PATH" -type f \( )
first=1
for e in "${EXT_LIST[@]}"; do
  if [[ $first -eq 1 ]]; then
    FIND_CMD+=(-iname "*.$e")
    first=0
  else
    FIND_CMD+=(-o -iname "*.$e")
  fi
done
FIND_CMD+=( \) -print0 )

while IFS= read -r -d '' file; do
  if [[ "$DRY_RUN" == true ]]; then
    info "[DRY RUN] Would delete: $file"
  else
    log "Deleting: $file"
    rm -f -- "$file"
  fi
done < <("${FIND_CMD[@]}")

log "Completed."
