#!/usr/bin/env bash

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
. "$SCRIPT_DIR/utils.sh" --source-only

set -euo pipefail

# v2.0.3

info "Running command in $(pwd)"

# Usage:
#   files-under-size --path=./ --size=1MB [--dry-run]

SIZE=""
PATH_ARG=""
DRY_RUN=false

# Parse arguments
while [[ $# -gt 0 ]]; do
  case "$1" in
    --size=*)
      SIZE="${1#*=}";
      shift
      ;;
    --path=*)
      PATH_ARG="${1#*=}";
      shift
      ;;
    --dry-run)
      DRY_RUN=true
      shift
      ;;
    -h|--help)
      warning "Usage: $0 --path=/path/to/media --size=1MB [--dry-run]"
      exit 0
      ;;
    *)
      warning "Unknown argument: $1"
      warning "Usage: $0 --path=/path/to/media --size=1MB [--dry-run]"
      exit 1
      ;;
  esac
done

note "Scanning: $PATH_ARG"
note "Size threshold: $SIZE"
note "Dry run: $DRY_RUN"
note "----------------------------------------------------"

if [[ -z "$SIZE" || -z "$PATH_ARG" ]]; then
  echo "Usage: $0 --size=1MB --path=/path/to/dir [--dry-run]" >&2
  exit 1
fi

to_lower() { printf '%s' "$1" | tr '[:upper:]' '[:lower:]'; }

parse_bytes() {
  local s n u mult=1
  s="$(to_lower "$(echo "$1" | tr -d ' ')")"
  n="${s%%[a-z]*}"; u="${s#$n}"
  [[ -z "$n" ]] && { echo "Invalid --size: $1" >&2; exit 1; }
  case "$u" in
    ""|"b") mult=1 ;;
    k|kb|kib) mult=1024 ;;
    m|mb|mib) mult=1048576 ;;
    g|gb|gib) mult=1073741824 ;;
    *) echo "Invalid size unit in --size: $1" >&2; exit 1 ;;
  esac
  echo $(( n * mult ))
}

LIMIT_BYTES="$(parse_bytes "$SIZE")"
LIMIT_PLUS_1_BYTES=$((LIMIT_BYTES + 1))

exts=(mp4 mkv avi mov flv wmv webm mpeg mpg m4v)

FIND_CMD=(find "$PATH_ARG" -type f \( )
first=1

for e in "${exts[@]}"; do
  if [[ $first -eq 1 ]]; then
    FIND_CMD+=(-iname "*.$e")
    first=0
  else
    FIND_CMD+=(-o -iname "*.$e")
  fi
done

FIND_CMD+=( \) -size "-${LIMIT_PLUS_1_BYTES}c" -print0 )

FILES=()
while IFS= read -r -d '' f; do FILES+=("$f"); done < <("${FIND_CMD[@]}")

TOTAL=${#FILES[@]}

if [[ $TOTAL -eq 0 ]]; then
  log "No matching video files ≤ $SIZE ($LIMIT_BYTES bytes)."
  exit 0
fi

info "Found $TOTAL file(s) ≤ $SIZE ($LIMIT_BYTES bytes)"
note "Threshold: $(printf "%'d" "$LIMIT_BYTES") bytes ($SIZE)"

COUNT=0

for f in "${FILES[@]}"; do
  ((COUNT++))

  FILESIZE=$(stat -f%z "$f" 2>/dev/null || stat -c%s "$f")

  log "File size: $(format_bytes "$FILESIZE")"

  if $DRY_RUN; then
    warning "[${COUNT}/${TOTAL}] Would delete: $(format_bytes "$FILESIZE") - $f"
  else
    warning "[${COUNT}/${TOTAL}] Deleting: $(format_bytes "$FILESIZE") - $f"
    rm -f -- "$f"
  fi
done

log "Done."
