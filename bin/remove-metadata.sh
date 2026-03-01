#!/opt/homebrew/bin/bash

. ~/bin/utils.sh --source-only

# Default values
TARGET_PATH=""

# Common video extensions (case-insensitive in exiftool)
DEFAULT_EXTS=(mp4 mov m4v mkv avi wmv mpg mpeg webm flv ts m2ts 3gp 3g2 ogv)

# Optional: allow overriding extensions via --exts=mp4,mov,...
USER_EXTS=()

# Help
usage() {
  cat <<EOF
Usage: $0 --path=/path/to/files [--exts=comma,separated,exts]

Removes all metadata from video files recursively under the given path.
Uses: exiftool -all= -overwrite_original -r -ext <ext>... -progress

Options:
  --path=DIR          Directory to scan (required)
  --exts=LIST         Comma-separated list of file extensions to process
                      (default: ${DEFAULT_EXTS[*]})
  --help              Show this help
EOF
}

# Parse arguments
for arg in "$@"; do
  case $arg in
    --path=*)
      TARGET_PATH="${arg#*=}"
      ;;
    --exts=*)
      IFS=',' read -r -a USER_EXTS <<< "${arg#*=}"
      ;;
    --help|-h)
      usage; exit 0
      ;;
    *)
      echo "Unknown option: $arg"
      usage; exit 1
      ;;
  esac
done

# Validate path
if [[ -z "$TARGET_PATH" ]]; then
  error "Error: --path must be specified"
  usage; exit 1
fi
if [[ ! -d "$TARGET_PATH" ]]; then
  error "Error: Path '$TARGET_PATH' does not exist or is not a directory."
  exit 1
fi

# Check exiftool availability
if ! command -v exiftool >/dev/null 2>&1; then
  error "Error: exiftool not found. Install exiftool and retry."
  exit 1
fi

# Choose extensions: user-provided or defaults
EXTS=("${USER_EXTS[@]:-${DEFAULT_EXTS[@]}}")

# Build -ext args
EXT_ARGS=()
for ext in "${EXTS[@]}"; do
  # Trim whitespace just in case
  clean_ext="$(echo -n "$ext" | tr -d '[:space:]')"
  [[ -n "$clean_ext" ]] && EXT_ARGS+=( -ext "$clean_ext" )
done

if [[ ${#EXT_ARGS[@]} -eq 0 ]]; then
  error "Error: No valid extensions provided."
  exit 1
fi

info "Removing metadata from extensions: ${EXTS[*]}"
info "Target path: $TARGET_PATH"

# Preview: list files exiftool will process (ignores Apple '._' files)
info "Listing candidate files:"
exiftool -r -i '*/._*' "${EXT_ARGS[@]}" -q -p '$FilePath' "$TARGET_PATH"

# Run exiftool (ignore Apple resource fork files)
exiftool -all= -overwrite_original -r -progress \
  -i '*/._*' \
  "${EXT_ARGS[@]}" "$TARGET_PATH"

log "Done."