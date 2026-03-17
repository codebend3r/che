#!/usr/bin/env bash

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
. "$SCRIPT_DIR/utils.sh" --source-only

set -euo pipefail

# v2.0.4

info "Running command in $(pwd)"

# Usage:
#   largest-tv-shows --path=/path/to/tv [--limit=20] [--full-path]

ROOT_DIR="${1:-}"
LIMIT="${LIMIT:-20}"
SHOW_FULL_PATH=false

while [[ $# -gt 0 ]]; do
  case "$1" in
    --path=*)
      ROOT_DIR="${1#*=}";
      shift
      ;;
    --limit=*)
      LIMIT="${1#*=}"
      shift
      ;;
    --full-path)
      SHOW_FULL_PATH=true
      shift
      ;;
    --length=*)
      LIST_LENGTH="${1#*=}"
      [[ -z "$LIST_LENGTH" || ! "$LIST_LENGTH" =~ ^[0-9]+$ ]]
      shift
      ;;
    -h|--help)
      warning "Usage: $0 --path=/path/to/media [--length=10] [--full-path]"
      exit 0
      ;;
    *)
      warning "Unknown argument: $1"
      warning "Usage: $0 --path=/path/to/media [--length=10] [--full-path]"
      exit 1
      ;;
  esac
done

note "Searching in: $ROOT_DIR"
note "Limit: ${LIMIT}"
note "Show full path: ${SHOW_FULL_PATH}"

if [[ -z "$ROOT_DIR" ]]; then
  usage
  exit 1
fi

if [[ ! -d "$ROOT_DIR" ]]; then
  echo "Error: '$ROOT_DIR' is not a valid directory" >&2
  exit 1
fi

if ! [[ "$LIMIT" =~ ^[0-9]+$ ]] || [[ "$LIMIT" -lt 1 ]]; then
  echo "Error: --limit must be a positive integer" >&2
  exit 1
fi

tmp_file="$(mktemp)"
trap 'rm -f "$tmp_file"' EXIT

find "$ROOT_DIR" -mindepth 2 -maxdepth 2 -type d | while IFS= read -r show_dir; do
  letter_dir="$(basename "$(dirname "$show_dir")")"

  # Only count folders that are directly inside A-Z or # buckets.
  # This excludes things like Requests automatically.
  if [[ "$letter_dir" =~ ^[A-Z]$|^#$ ]]; then
    size_kb="$(du -sk "$show_dir" | awk '{print $1}')"
    show_name="$(basename "$show_dir")"
    printf "%s\t%s\t%s\n" "$size_kb" "$show_name" "$show_dir"
  fi
done > "$tmp_file"

sort -rn "$tmp_file" | head -n "$LIMIT" | while IFS=$'\t' read -r size_kb show_name show_dir; do
  formatted_size="$(human_size "$size_kb")"

  if [[ "$SHOW_FULL_PATH" == true ]]; then
    printf "%-12s %s\n" "$formatted_size" "$show_dir"
  else
    printf "%-12s %s\n" "$formatted_size" "$show_name"
  fi
done