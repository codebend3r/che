#!/usr/bin/env bash

. ~/bin/utils.sh --source-only

set -euo pipefail

# v2.0.1

info "Running command in $(pwd)"

# Usage:
#   fix-codecs --path=./ --delete-original=true

TARGET_PATH=""
DELETE_ORIGINAL=false

# Parse arguments
while [[ $# -gt 0 ]]; do
  case "$1" in
    --path=*)
      TARGET_PATH="${1#*=}"
      shift
      ;;
    --delete-original=*)
      DELETE_ORIGINAL=true
      shift
      ;;
    -h|--help)
      warning "Usage: $0 --path=/path/to/media [--delete-original=true]"
      warning "Default: --delete-original=false"
      exit 0
      ;;
    *)
      warning "Unknown argument: $1"
      warning "Usage: $0 --path=/path/to/media [--delete-original=true]"
      exit 1
      ;;
  esac
done

if [[ -z "$TARGET_PATH" ]]; then
  warning "Error: You must provide a path with --path="
  exit 1
fi

if ! command -v ffmpeg &>/dev/null; then
  warning "Error: ffmpeg is not installed. Install FFmpeg first."
  exit 1
fi

note "Scanning: $TARGET_PATH"
note "Delete original after conversion: $DELETE_ORIGINAL"
note "----------------------------------------------------"

find "$TARGET_PATH" -type f \( -iname "*.mp4" -o -iname "*.mkv" -o -iname "*.mov" -o -iname "*.avi" \) | while read -r file; do
  dir=$(dirname "$file")
  base=$(basename "$file")
  filename="${base%.*}"
  output="$dir/${filename}_fixed.mp4"

  log "Processing: $file"
  
  ffmpeg -i "$file" \
    -map 0:v:0 -map 0:a:0 -map 0:s:0? \
    -c:v libx265 -preset slow -crf 22 \
    -c:a aac -b:a 384k \
    -c:s mov_text \
    -movflags +faststart \
    -max_muxing_queue_size 9999 \
    "$output"

  log "✅ Converted to: $output"

  if [[ "$DELETE_ORIGINAL" == "true" ]]; then
    rm -f "$file"
    warning "🗑 Deleted original: $file"
  fi
done