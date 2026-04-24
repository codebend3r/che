#!/opt/homebrew/bin/bash

. ~/bin/utils.sh --source-only

set -euo pipefail

ROOT_DIR=""
VERBOSE=false
# Allowed codecs for Direct Play (common safe set)
ALLOWED_VIDEO_CODECS=("h264" "hevc")
ALLOWED_AUDIO_CODECS=("aac" "ac3" "eac3")
ALLOWED_CONTAINERS=("mov" "mp4" "mkv")

# Parse arguments
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
      echo "Usage: $0 --path=/path/to/media"
      exit 0
      ;;
    *)
      echo "Unknown argument: $1"
      echo "Usage: $0 --path=/path/to/media"
      exit 1
      ;;
  esac
done

note "Scanning: $ROOT_DIR"
note "Verbose: $VERBOSE"
note "----------------------------------------------------"

if [[ -z "$ROOT_DIR" ]]; then
  echo "Error: You must provide a path with --path="
  exit 1
fi

if ! command -v ffprobe &>/dev/null; then
  echo "Error: ffprobe is not installed. Install FFmpeg first."
  exit 1
fi

echo "Scanning for problematic codecs in: $ROOT_DIR"
echo "Allowed Video: ${ALLOWED_VIDEO_CODECS[*]}"
echo "Allowed Audio: ${ALLOWED_AUDIO_CODECS[*]}"
echo "Allowed Containers: ${ALLOWED_CONTAINERS[*]}"
echo "----------------------------------------------------"

find "$ROOT_DIR" -type f \( -iname "*.mp4" -o -iname "*.mkv" -o -iname "*.mov" -o -iname "*.avi" \) | while read -r file; do
  # Extract codecs and container
  container_ext="${file##*.}"
  video_codec=$(ffprobe -v error -select_streams v:0 -show_entries stream=codec_name -of csv=p=0 "$file" || echo "unknown")
  audio_codec=$(ffprobe -v error -select_streams a:0 -show_entries stream=codec_name -of csv=p=0 "$file" || echo "unknown")

  # Lowercase values
  container_ext=$(echo "$container_ext" | tr '[:upper:]' '[:lower:]')
  video_codec=$(echo "$video_codec" | tr '[:upper:]' '[:lower:]')
  audio_codec=$(echo "$audio_codec" | tr '[:upper:]' '[:lower:]')

  video_ok=false
  audio_ok=false
  container_ok=false

  for vc in "${ALLOWED_VIDEO_CODECS[@]}"; do
    [[ "$video_codec" == "$vc" ]] && video_ok=true
  done
  for ac in "${ALLOWED_AUDIO_CODECS[@]}"; do
    [[ "$audio_codec" == "$ac" ]] && audio_ok=true
  done
  for cc in "${ALLOWED_CONTAINERS[@]}"; do
    [[ "$container_ext" == "$cc" ]] && container_ok=true
  done

  if [[ "$video_ok" == false || "$audio_ok" == false || "$container_ok" == false ]]; then
    warning "❌ $file"
    warning "Container: $container_ext | Video: $video_codec | Audio: $audio_codec"
  else
    if [[ "$VERBOSE" == true ]]; then
      log "✅ $file"
      log "Container: $container_ext | Video: $video_codec | Audio: $audio_codec"
    fi
  fi
done