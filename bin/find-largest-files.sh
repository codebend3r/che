#!/usr/bin/env bash

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
. "$SCRIPT_DIR/utils.sh" --source-only

set -euo pipefail

# v2.0.3
info "Running command in $(pwd)"

# Usage:
#   find-largest-files --path=./ [--length=10] [--full-path]

SHOW_FULL_PATH=false
LIST_LENGTH=10
SEARCH_PATH="."

while [[ $# -gt 0 ]]; do
  case "$1" in
    --full-path)
      SHOW_FULL_PATH=true
      shift
      ;;
    --length=*)
      LIST_LENGTH="${1#*=}"
      [[ -z "$LIST_LENGTH" || ! "$LIST_LENGTH" =~ ^[0-9]+$ ]]
      shift
      ;;
    --path=*)
      SEARCH_PATH="${1#*=}";
      [[ -z "$SEARCH_PATH" ]]
      shift
      ;;
    -h|--help)
      warning "Usage: $0 --path=/path/to/media [--length=10] [--full-path]"
      exit 0
      ;;
    *)
      warning "Unknown argument: $1"
      warning "Usage: $0 --path=/path/to/media [--length=10] [--full-path]"
      exit 1
      ;;
  esac
done

log "Searching in: $SEARCH_PATH"
log "List length: ${LIST_LENGTH}"
log "Show full path: ${SHOW_FULL_PATH}"

if [[ ! -d "$SEARCH_PATH" ]]; then
  echo "Error: Path does not exist or is not a directory: $SEARCH_PATH" >&2
  exit 1
fi

if [[ "$SHOW_FULL_PATH" == true ]]; then
  FIND_CMD=(find "$SEARCH_PATH" -type f -print0)
else
  FIND_CMD=(find "$SEARCH_PATH" -type f -print0)
fi

"${FIND_CMD[@]}" | \
  xargs -0 stat -f "%z|%N" 2>/dev/null | \
  sort -t'|' -nrk1 | \
  head -n "$LIST_LENGTH" | \
  while IFS='|' read -r size file; do
    if [[ "$SHOW_FULL_PATH" == true ]]; then
      # info "$(human_size "$size") $file"
      printf "%12s  %s\n" "$(human_size "$size")" "$file"
    else
      # info "$(human_size "$size")" "$(basename "$file")"
      printf "%12s  %s\n" "$(human_size "$size")" "$(basename "$file")"
    fi
  done