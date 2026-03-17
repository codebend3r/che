#!/opt/homebrew/bin/bash

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
. "$SCRIPT_DIR/utils.sh" --source-only

set -euo pipefail

# v2.0.3

info "Running command in $(pwd)"

# Usage:
#   delete-smb-files --path=./ [--dry-run]

ROOT_DIR=""
DRY_RUN=false

# Parse arguments
while [[ $# -gt 0 ]]; do
  case "$1" in
    --path=*)
      ROOT_DIR="${1#*=}"
      shift 2
      ;;
    --dry-run)
      DRY_RUN=true
      shift
      ;;
    -h|--help)
      echo "Usage: $0 --path=/path/to/media [--dry-run]"
      exit 0
      ;;
    *)
      warning "Unknown option: $1"
      warning "Usage: $0 --path /directory/to/scan"
      exit 1
      ;;
  esac
done

note "Searching in: $ROOT_DIR"
note "Dry run: ${DRY_RUN}"

if [[ -z "$ROOT_DIR" ]]; then
  warning "Error: --path is required."
  warning "Usage: $0 --path /directory/to/scan"
  exit 1
fi

if [[ ! -d "$ROOT_DIR" ]]; then
  warning "Error: Directory does not exist: $ROOT_DIR"
  exit 1
fi

info "Scanning for .smbdelete* files under: $ROOT_DIR"

if [[ "$DRY_RUN" == true ]]; then
  info "Dry run mode: no files will be deleted."
  # Allow find to error without killing the script
  find "$ROOT_DIR" -type f -name ".smbdelete*" -print || true
else
  # -delete may fail with 'Resource busy' for some files; don't exit the script
  find "$ROOT_DIR" -type f -name ".smbdelete*" -print -delete 2>/dev/null || true
fi