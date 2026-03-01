#!/opt/homebrew/bin/bash

. ~/bin/utils.sh --source-only

set -euo pipefail

# v2.0.1

info "Running command in $(pwd)"

# Usage:
#   find-video-mkv-issues --path=./

# Default scan path
ROOT="."

# Parse args
for arg in "$@"; do
  case $arg in
    --path=*)
      ROOT="${arg#*=}"
      shift
      ;;
    *)
      echo "Unknown option: $arg"
      echo "Usage: $0 --path=/path/to/media"
      exit 1
      ;;
  esac
done

note "Scanning: $ROOT"
note "----------------------------------------------------"

count=0

find "$ROOT" -type f -iname '*.mkv' -print0 |
while IFS= read -r -d '' f; do
  codec="$(ffprobe -v error -select_streams v:0 \
           -show_entries stream=codec_name \
           -of default=nw=1:nk=1 "$f" 2>/dev/null || true)"
  case "$codec" in
    av1|vc1|wmv3)
      printf '%s\n' "$f"
      count=$((count+1))
      ;;
    *) : ;;
  esac
done

echo "Done. Found $count MKV(s) with AV1/VC-1/WMV3."