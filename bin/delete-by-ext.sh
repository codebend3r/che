#!/usr/bin/env bash

. ~/bin/utils.sh --source-only

set -euo pipefail

# v2.0.1

info "Running command in $(pwd)"

# Usage:
#   delete-by-ext --path=./ --ext=m3u,nfo,sfv,jpg,png,txt,log,cue,srr [--dry-run] [--verbose]

DRY_RUN=false
VERBOSE=false
ROOT_PATH=""
EXT_LIST=(m3u nfo sfv jpg png txt log cue srr)

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
    --dry-run)
      DRY_RUN=true
      shift
      ;;
    --verbose)
      VERBOSE=true
      shift
      ;;
    -h|--help)
      warning "Usage: delete-by-ext --path=/dir --ext=jpg,png,mp4 [--dry-run] [--verbose]"
      exit 0
      ;;
    *)
      warning "Unknown argument: $1"
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

EXT_PATTERN="$(IFS='|'; echo "${EXT_LIST[*]}")"

while IFS= read -r -d '' file; do
  if [[ "$DRY_RUN" == true ]]; then
    info "[DRY RUN] Would delete: $file"
  else
    log "Deleting: $file"
    rm -f "$file"
  fi
done < <(
  find "$ROOT_PATH" -type f \
    | grep -E "\.($EXT_PATTERN)$" \
    | tr '\n' '\0'
)

log "Completed."
