#!/usr/bin/env bash

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
. "$SCRIPT_DIR/../utils.sh" --source-only

set -euo pipefail

# v1.0.0

# Detect videos with the green/magenta chroma decoding artifact.
#
# Thin wrapper around detect-green-magenta-videos.py — forwards all args
# verbatim. The Python script handles flag parsing.
#
# Usage:
#   detect-green-magenta-videos <path> [<path>...] [--samples=N] [--threshold=F] [--verbose]
#
# Exit codes (from the Python script):
#   0 — no flagged videos
#   1 — at least one flagged video
#   2 — no video files found

usage() {
  cat <<EOF
Usage:
  $(basename "$0") <path> [<path>...] [--samples=N] [--threshold=F] [--verbose]

Description:
  Detect videos with the "green and magenta" chroma decoding artifact by
  sampling frames and measuring how much of the saturated color sits in
  the green or magenta hue bands.

Options:
  <path>          One or more video files or directories (dirs scanned recursively)
  --samples=N     Frames to sample per video (default: 20)
  --threshold=F   Fraction of saturated pixels in green/magenta to flag (default: 0.80)
  --verbose, -v   Print every video, not just flagged ones
  --help, -h      Show help

Examples:
  $(basename "$0") /path/to/video.mp4
  $(basename "$0") /Volumes/Media/Movies --verbose
  $(basename "$0") ./vids --samples=40 --threshold=0.7

Requires:
  python3 with opencv-python and numpy installed
    pip install opencv-python numpy
EOF
}

require_binary() {
  local bin=$1

  if ! command -v "$bin" >/dev/null 2>&1; then
    warning "Missing required binary: $bin"
    exit 1
  fi
}

require_binary python3

if [[ $# -eq 0 ]]; then
  usage
  exit 1
fi

case "${1:-}" in
  --help|-h)
    usage
    exit 0
    ;;
esac

PY_SCRIPT="$SCRIPT_DIR/detect-green-magenta-videos.py"

if [[ ! -f "$PY_SCRIPT" ]]; then
  warning "Python script not found: $PY_SCRIPT"
  exit 1
fi

# Verify required Python modules are importable before launching.
if ! python3 -c 'import cv2, numpy' >/dev/null 2>&1; then
  warning "python3 is missing required modules. Run:"
  warning "  pip install opencv-python numpy"
  exit 1
fi

info "Running command in $(pwd)"
note "Scanning: $*"
note "----------------------------------------------------"

exec python3 "$PY_SCRIPT" "$@"
