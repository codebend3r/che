#!/opt/homebrew/bin/bash

. ~/bin/utils.sh --source-only

set -euo pipefail

# v2.0.1

info "Running command in $(pwd)"

# Usage:
#   validate-video-files --path=./ [--verbose]

# Default path
ROOT_DIR=""
VERBOSE=false

# Argument parsing
while [[ $# -gt 0 ]]; do
  case "$1" in
    --path=*)
      ROOT_DIR="${1#*=}"
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
      warning "Usage: $0 --path=/path/to/media [--verbose]"
      exit 0
      ;;
    *)
      warning "Unknown argument: $1"
      warning "Usage: $0 --path /path/to/check"
      exit 1
      ;;
  esac
done

# Validate path
if [[ ! -d "$ROOT_DIR" ]]; then
  warning "❌ Error: '$ROOT_DIR' is not a valid directory"
  exit 1
fi

# Check if mpv is installed
if ! command -v mpv >/dev/null 2>&1; then
  warning "❌ Error: 'mpv' is not installed."
  warning "Install it using Homebrew:"
  warning "  brew install mpv"
  exit 1
fi

# Temp file for logging errors
TMP_LOG=$(mktemp)

# Recursively check .mp4 and .mkv files for playability
find "$ROOT_DIR" -type f \( -iname "*.mp4" -o -iname "*.mkv" \) | while IFS= read -r file; do
  if [[ -z "$VERBOSE" ]]; then
    info "Checking: $file"
  fi


  mpv --no-audio --vo=null --really-quiet --frames=1 "$file" >"$TMP_LOG" 2>&1

  if [[ -s "$TMP_LOG" ]]; then
    warning "❌ Unplayable or error in: $file"
  fi

  # Clear the log file before the next check
  : > "$TMP_LOG"
done

# Clean up temp log
rm -f "$TMP_LOG"
