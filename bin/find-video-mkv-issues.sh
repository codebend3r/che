#!/usr/bin/env bash

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
. "$SCRIPT_DIR/utils.sh" --source-only

set -euo pipefail

# v2.1.0

info "Running command in $(pwd)"

# Usage:
#   find-video-mkv-issues --path=./ [--recursive]

usage() {
  cat <<EOF
Usage:
  $(basename "$0") --path=/media/path [--recursive]

Description:
  Scan MKV files and estimate Plex direct-play compatibility.

Options:
  --path=PATH     Required path to scan
  --recursive     Recursively scan subfolders (default: false)
  --help          Show help

Examples:
  $(basename "$0") --path=./Movies
  $(basename "$0") --path=/mnt/media --recursive
EOF
}

#
# Validate required binaries
#

require_binary() {
  local bin=$1

  if ! command -v "$bin" >/dev/null 2>&1; then
    warning "Missing required binary: $bin"
    exit 1
  fi
}

require_binary ffprobe
require_binary find
require_binary bc

#
# Defaults
#

ROOT=""
RECURSIVE=false

#
# Parse args
#

for arg in "$@"; do
  case "$arg" in
    --path=*)
      ROOT="${arg#*=}"
      ;;
    --recursive)
      RECURSIVE=true
      ;;
    --help|-h)
      usage
      exit 0
      ;;
    *)
      warning "Unknown option: $arg"
      usage
      exit 1
      ;;
  esac
done

#
# Validate args
#

if [[ -z "$ROOT" ]]; then
  warning "--path is required"
  usage
  exit 1
fi

if [[ ! -d "$ROOT" ]]; then
  warning "Directory does not exist: $ROOT"
  exit 1
fi

note "Scanning: $ROOT"
note "Recursive: $RECURSIVE"
note "----------------------------------------------------"

#
# Build find args safely for set -u
#

declare -a FIND_ARGS

if [[ "$RECURSIVE" == false ]]; then
  FIND_ARGS=(-maxdepth 1)
else
  FIND_ARGS=()
fi

#
# Stats
#

total=0
excellent=0
good=0
poor=0
bad=0

#
# Get media metadata
#

get_ffprobe_value() {
  local file=$1
  local stream=$2
  local entry=$3

  ffprobe \
    -v error \
    ${stream:+-select_streams "$stream"} \
    -show_entries "$entry" \
    -of default=noprint_wrappers=1:nokey=1 \
    "$file" 2>/dev/null || true
}

#
# Rate Plex compatibility
#

rate_video() {
  local video_codec=$1
  local audio_codec=$2
  local subtitle_codec=$3
  local width=$4
  local bitrate=$5

  local score=10
  local reasons=()

  #
  # Video codec scoring
  #

  case "$video_codec" in
    h264)
      ;;
    hevc|h265)
      score=$((score - 1))
      reasons+=("HEVC may transcode on older clients")
      ;;
    vp9)
      score=$((score - 3))
      reasons+=("VP9 support inconsistent")
      ;;
    av1)
      score=$((score - 5))
      reasons+=("AV1 unsupported on many Plex devices")
      ;;
    vc1|wmv3)
      score=$((score - 7))
      reasons+=("Legacy video codec")
      ;;
    mpeg2video)
      score=$((score - 5))
      reasons+=("MPEG2 commonly transcoded")
      ;;
    *)
      score=$((score - 8))
      reasons+=("Unknown or niche video codec")
      ;;
  esac

  #
  # Audio codec scoring
  #

  case "$audio_codec" in
    aac)
      ;;
    ac3|eac3)
      score=$((score - 1))
      ;;
    dts)
      score=$((score - 3))
      reasons+=("DTS unsupported on many TVs/mobile devices")
      ;;
    truehd)
      score=$((score - 5))
      reasons+=("TrueHD frequently transcoded")
      ;;
    flac)
      score=$((score - 3))
      reasons+=("FLAC audio may transcode")
      ;;
    mp2)
      score=$((score - 5))
      reasons+=("MP2 audio uncommon")
      ;;
    *)
      score=$((score - 4))
      reasons+=("Unknown or niche audio codec")
      ;;
  esac

  #
  # Subtitle scoring
  #

  case "$subtitle_codec" in
    pgs|hdmv_pgs_subtitle)
      score=$((score - 2))
      reasons+=("PGS subtitles may force transcoding")
      ;;
    dvd_subtitle)
      score=$((score - 2))
      reasons+=("Image subtitles may transcode")
      ;;
    *)
      ;;
  esac

  #
  # Resolution scoring
  #

  if [[ "$width" =~ ^[0-9]+$ ]]; then
    if (( width >= 3840 )); then
      score=$((score - 1))
      reasons+=("4K playback may struggle on weaker devices")
    fi
  fi

  #
  # Bitrate scoring
  #

  if [[ "$bitrate" =~ ^[0-9]+$ ]]; then
    local mbps=$((bitrate / 1000000))

    if (( mbps > 60 )); then
      score=$((score - 2))
      reasons+=("Very high bitrate")
    elif (( mbps > 30 )); then
      score=$((score - 1))
      reasons+=("High bitrate")
    fi
  fi

  #
  # Clamp score
  #

  (( score < 0 )) && score=0
  (( score > 10 )) && score=10

  printf '%s|' "$score"

  if (( ${#reasons[@]} > 0 )); then
    printf '%s' "$(IFS='; '; echo "${reasons[*]}")"
  else
    printf 'Excellent Plex compatibility'
  fi
}

#
# Scan files
#

while IFS= read -r -d '' file; do
  total=$((total + 1))

  note "Checking:"
  echo "  $file"

  #
  # Verify file is readable
  #

  if ! ffprobe -v error "$file" >/dev/null 2>&1; then
    warning "  Corrupt or unreadable file"
    echo

    bad=$((bad + 1))
    continue
  fi

  #
  # Collect metadata
  #

  video_codec="$(
    get_ffprobe_value \
      "$file" \
      "v:0" \
      "stream=codec_name"
  )"

  audio_codec="$(
    get_ffprobe_value \
      "$file" \
      "a:0" \
      "stream=codec_name"
  )"

  subtitle_codec="$(
    get_ffprobe_value \
      "$file" \
      "s:0" \
      "stream=codec_name"
  )"

  width="$(
    get_ffprobe_value \
      "$file" \
      "v:0" \
      "stream=width"
  )"

  bitrate="$(
    get_ffprobe_value \
      "$file" \
      "" \
      "format=bit_rate"
  )"

  filesize="$(
    stat -f%z "$file" 2>/dev/null ||
    stat -c%s "$file" 2>/dev/null ||
    echo 0
  )"

  #
  # Rate compatibility
  #

  result="$(
    rate_video \
      "${video_codec:-unknown}" \
      "${audio_codec:-unknown}" \
      "${subtitle_codec:-none}" \
      "${width:-0}" \
      "${bitrate:-0}"
  )"

  score="${result%%|*}"
  notes="${result#*|}"

  #
  # Output
  #

  echo "  Size      : $(format_bytes "$filesize")"
  echo "  Video     : ${video_codec:-unknown}"
  echo "  Audio     : ${audio_codec:-unknown}"
  echo "  Subtitles : ${subtitle_codec:-none}"

  if [[ "$width" =~ ^[0-9]+$ ]]; then
    echo "  Resolution: ${width}px"
  fi

  if [[ "$bitrate" =~ ^[0-9]+$ ]]; then
    echo "  Bitrate   : $((bitrate / 1000000)) Mbps"
  fi

  if (( score >= 9 )); then
    success "  Plex Score: ${score}/10"
    excellent=$((excellent + 1))
  elif (( score >= 7 )); then
    info "  Plex Score: ${score}/10"
    good=$((good + 1))
  elif (( score >= 4 )); then
    note "  Plex Score: ${score}/10"
    poor=$((poor + 1))
  else
    warning "  Plex Score: ${score}/10"
    bad=$((bad + 1))
  fi

  echo "  Notes     : $notes"
  echo

done < <(
  find "$ROOT" \
    ${FIND_ARGS[@]+"${FIND_ARGS[@]}"} \
    -type f \
    -iname '*.mkv' \
    -print0
)

#
# Summary
#

note "----------------------------------------------------"

success "Scan complete"

echo
echo "Total Files : $total"
echo "Excellent   : $excellent"
echo "Good        : $good"
echo "Poor        : $poor"
echo "Bad         : $bad"