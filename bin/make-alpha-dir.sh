#!/opt/homebrew/bin/bash

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
. "$SCRIPT_DIR/utils.sh" --source-only

set -euo pipefail

# Default path
TARGET_PATH=""

# Argument parsing
while [[ $# -gt 0 ]]; do
  case "$1" in
    --path=*)
      TARGET_PATH="${1#*=}"
      shift
      ;;
    -h|--help)
      echo "Usage: $0 --path=/path/to/parent"
      exit 0
      ;;
    *)
      echo "Unknown argument: $1"
      echo "Usage: $0 --path=/path/to/parent"
      exit 1
      ;;
  esac
done

# Fallback to current directory if not provided
if [[ -z "${TARGET_PATH}" ]]; then
  TARGET_PATH="."
fi

mkdir -p "$TARGET_PATH"
cd "$TARGET_PATH"

# Create "#" and A–Z
mkdir -p -- '#' {A..Z}