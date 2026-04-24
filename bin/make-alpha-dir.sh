#!/opt/homebrew/bin/bash

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
. "$SCRIPT_DIR/utils.sh" --source-only

set -euo pipefail

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
if [[ -z "${ROOT_DIR}" ]]; then
  ROOT_DIR="."
fi

mkdir -p "$ROOT_DIR"
cd "$ROOT_DIR"

# Create "#" and A–Z
mkdir -p -- '#' {A..Z}