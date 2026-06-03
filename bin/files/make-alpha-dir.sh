#!/opt/homebrew/bin/bash

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=bin/utils.sh
. "$SCRIPT_DIR/../utils.sh" --source-only

set -euo pipefail

info "Running command in $(pwd)"

# Usage:
#   make-alpha-dir [--path=/path/to/dir]

# Default path
ROOT_DIR=""

# ⚙️  CLI — long flags only (see ../utils.sh).
while [[ $# -gt 0 ]]; do
  case "$1" in
    --path=*)
      ROOT_DIR="${1#*=}"
      shift
      ;;
    -h|--help)
      info "📋 Usage: $0 [--path=/path/to/parent]  (defaults to .)"
      exit 0
      ;;
    *)
      warning "❌ Unknown argument: $1"
      warning "📋 Usage: $0 [--path=/path/to/parent]"
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