#!/opt/homebrew/bin/bash

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
. "$SCRIPT_DIR/utils.sh" --source-only

set -euo pipefail

# v2.0.3

info "Running command in $(pwd)"

# Usage:
#   delete-empty-folders --path=./ --dry-run=true

DRY_RUN=false
VERBOSE=false
ROOT_DIR=""
DELETED_COUNT=0

while [[ $# -gt 0 ]]; do
  case "$1" in
    --path=*) ROOT_DIR="${1#*=}"; shift ;;
    --dry-run=*) DRY_RUN="${1#*=}"; shift ;;
    --dry-run) DRY_RUN=true; shift ;;
    --verbose=*) VERBOSE="${1#*=}"; shift ;;
    --verbose) VERBOSE=true; shift ;;
    -h|--help)
      echo "Usage: $0 --path=/path/to/media [--dry-run] [--verbose]"
      exit 0
      ;;
    *)
      warning "Unknown argument: $1"
      echo "Usage: $0 --path=/path/to/media [--dry-run] [--verbose]"
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

# Deepest-first directory traversal
while IFS= read -r -d '' dir; do
  # Skip hidden directories
  if [[ "$(basename "$dir")" == .* ]]; then
    continue
  fi

  # Count visible files inside this folder (recursively)
  file_count=$(find "$dir" -type f -not -path '*/.*' | wc -l | tr -d ' ')

  # Verbose output
  if $VERBOSE; then
    warning "Scanned: $dir (files: $file_count)"
  fi

  # If no visible files, delete folder
  if (( file_count == 0 )); then
    if $DRY_RUN; then
      log "[DRY-RUN] Would delete: $dir"
    else
      rm -rf "$dir"
      log "Deleted: $dir"
    fi
    ((DELETED_COUNT++))
  fi
done < <(find "$ROOT_DIR" -type d -not -path '*/.*' -print0 | sort -rz)

echo "Total deleted directories: $DELETED_COUNT"
