#!/opt/homebrew/bin/bash

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=bin/utils.sh
. "$SCRIPT_DIR/../utils.sh" --source-only

set -euo pipefail

# v2.0.4

info "Running command in $(pwd)"

# Usage:
#   find-movie-by-year --year=YYYY [--path=/path/to/search]

# Default values
ROOT_DIR="."
YEAR=""

# ⚙️  CLI — long flags only (see ../utils.sh).
while [[ $# -gt 0 ]]; do
  case "$1" in
    --path=*)
      ROOT_DIR="${1#*=}"
      shift
      ;;
    --year=*)
      YEAR="${1#*=}"
      shift
      ;;
    -h|--help)
      info "📋 Usage: $0 --year=YYYY [--path=/path/to/search]"
      info "Example: $0 --year=2025 --path=/movies"
      exit 0
      ;;
    *)
      warning "❌ Unknown argument: $1"
      warning "📋 Usage: $0 --year=YYYY [--path=/path/to/search]"
      exit 1
      ;;
  esac
done

if [[ -z "$YEAR" ]]; then
  warning "❌ --year is required"
  exit 1
fi

# Search for movies with the specified year in their filename
find "$ROOT_DIR" -type d -iname "*(${YEAR})" -print