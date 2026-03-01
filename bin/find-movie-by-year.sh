#!/opt/homebrew/bin/bash

. ~/bin/utils.sh --source-only

set -euo pipefail

# Default values
TARGET_PATH="."
YEAR=""

# Argument parsing
while [[ $# -gt 0 ]]; do
  case "$1" in
    --path=*)
      TARGET_PATH="${1#*=}"
      shift
      ;;
    --year=*)
      YEAR="${1#*=}"
      shift
      ;;
    -h|--help)
      echo "Usage: $0 --year=YYYY [--path=/path/to/search]"
      echo "Example: $0 --year=2025 --path=/movies"
      exit 0
      ;;
    *)
      echo "Unknown argument: $1"
      echo "Usage: $0 --year=YYYY [--path=/path/to/search]"
      exit 1
      ;;
  esac
done

if [[ -z "$YEAR" ]]; then
  echo "Error: --year is required"
  exit 1
fi

# Allowed movie file extensions (add more if needed)
EXTENSIONS="mp4|mkv|avi|mov|wmv|flv|webm"

# Search for movies with the specified year in their filename
find "$TARGET_PATH" -type d -iname "*(${YEAR})" -print
# find "$TARGET_PATH" -type f \
#   -iregex ".*\.\($EXTENSIONS\)" \
#   -iregex ".*\(${YEAR}\).*" \
#   -print