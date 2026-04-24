#!/opt/homebrew/bin/bash

. ~/bin/utils.sh --source-only

set -euo pipefail

# v2.0.0

info "Running command in $(pwd)"

# Usage:
#   scan-videos-audio-language --path=./

# Default path
ROOT_DIR=""

# Argument parsing
while [[ $# -gt 0 ]]; do
  case "$1" in
    --path=*)
      ROOT_DIR="${1#*=}"
      shift
      ;;
    -h|--help)
      echo "Usage: $0 --path=/path/to/media"
      exit 0
      ;;
    *)
      echo "Unknown argument: $1"
      echo "Usage: $0 --path /path/to/check"
      exit 1
      ;;
  esac
done

# Validate path
if [[ ! -d "$ROOT_DIR" ]]; then
  info "❌ Error: '$ROOT_DIR' is not a valid directory"
  exit 1
fi

# Check if ffprobe exists
if ! command -v ffprobe &>/dev/null; then
  warning "ffprobe (from ffmpeg) is required but not installed."
  exit 1
fi

# Video file extensions to check
EXTENSIONS="mp4|mkv|avi|mov|flv|wmv|webm"

# ANSI color codes
RESET="\033[0m"
declare -A LANG_COLOR=(
  ["eng"]="\033[32m"  # Green
  ["jpn"]="\033[31m"  # Red
  ["spa"]="\033[33m"  # Yellow
  ["fre"]="\033[34m"  # Blue
  ["ger"]="\033[35m"  # Magenta
  ["ita"]="\033[36m"  # Cyan
  ["kor"]="\033[95m"  # Light Magenta
  ["chi"]="\033[91m"  # Light Red
  ["por"]="\033[92m"  # Light Green
  ["rus"]="\033[94m"  # Light Blue
)

DEFAULT_COLOR="\033[90m" # Gray for unknown languages

# Find video files, sort alphabetically, and process each
find "$ROOT_DIR" -type f | grep -Ei "\.($EXTENSIONS)$" | sort | while read -r file; do
  info "File: $file"

  # Extract languages
  LANGS=$(ffprobe -v error -select_streams a \
    -show_entries stream_tags=language \
    -of csv=p=0 "$file" | sort | uniq)

  if [ -z "$LANGS" ]; then
    info "Audio language(s): ${DEFAULT_COLOR}Unknown or not tagged${RESET}"
  else
    IFS=$'\n'
    COLOR_LANGS=""
    for lang in $LANGS; do
      color="${LANG_COLOR[$lang]:-$DEFAULT_COLOR}"
      COLOR_LANGS+="${color}${lang}${RESET} "
    done
    info "Audio language(s): $COLOR_LANGS"
  fi
done