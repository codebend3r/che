#!/usr/bin/env bash

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
. "$SCRIPT_DIR/utils.sh" --source-only

set -euo pipefail

# v2.0.3

info "Running command in $(pwd)"

# Usage:
#   video-list --path=./ [--recursive] [--sort=alpha|fileSizeAsc|fileSizeDesc] [--with-folder]

DIR=""
RECURSE=false
SORT_METHOD="alpha"
WITH_FOLDER=false

while [[ $# -gt 0 ]]; do
  case "$1" in
    --path=*) DIR="${1#*=}"; shift ;;
    --recursive) RECURSE=true; shift ;;
    --with-folder) WITH_FOLDER=true; shift ;;
    --sort=*)
      SORT_METHOD="${1#*=}"
      case "$SORT_METHOD" in
        alpha|fileSizeAsc|fileSizeDesc) ;;
        *)
          echo "Error: Invalid sort method. Supported methods are alpha, fileSizeAsc, fileSizeDesc." >&2
          exit 1
          ;;
      esac
      shift
      ;;
    *)
      echo "Usage: $0 --path=/path [--recursive] [--sort=alpha|fileSizeAsc|fileSizeDesc] [--with-folder]" >&2
      exit 1
      ;;
  esac
done

note "Scanning: $DIR"
note "Recursive: $RECURSE"
note "Sort method: $SORT_METHOD"
note "With folder: $WITH_FOLDER"

[[ -z "$DIR" ]] && { echo "Error: --path is required" >&2; exit 1; }

FIND_CMD="find \"$DIR\""

if ! $RECURSE; then
  FIND_CMD+=" -maxdepth 1"
fi

FIND_CMD+=" -not -path '*/.*'"
FIND_CMD+=" -type f \\( -iname \"*.mp4\" -o -iname \"*.mkv\" \\)"

TMP_FILE=$(mktemp)

eval "$FIND_CMD" | while IFS= read -r file; do
  size=$(ls -l -- "$file" | awk '{print $5}')
  echo "$size|$file" >> "$TMP_FILE"
done

case "$SORT_METHOD" in
  fileSizeAsc)  sort -n  "$TMP_FILE" -o "$TMP_FILE" ;;
  fileSizeDesc) sort -nr "$TMP_FILE" -o "$TMP_FILE" ;;
  alpha)        sort -t'|' -k2 "$TMP_FILE" -o "$TMP_FILE" ;;
esac

while IFS='|' read -r size file; do
  size_human=$(human_size "$size")

  folder="$(basename "$(dirname "$file")")"
  filename="$(basename "$file")"

  if $WITH_FOLDER; then
    display="${CYAN}${folder}${NC}/${GREEN}${filename}${NC} ${YELLOW}[${size_human}]${NC}"
  else
    display="${GREEN}${filename}${NC} ${YELLOW}[${size_human}]${NC}"
  fi

  log "$display"
done < "$TMP_FILE"

rm "$TMP_FILE"