#!/usr/bin/env bash

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
. "$SCRIPT_DIR/utils.sh" --source-only

set -euo pipefail

# v2.1.1

info "Running command in $(pwd)"

# Recursively scans a TV library and identifies TV show folders by structure.
#
# A TV show folder is any folder that contains at least one direct child folder
# matching:
#   Season 1
#   Season 2
#   Season 10
# etc.
#
# Usage:
#   largest-tv-shows --path=/path/to/tv [--limit=20] [--full-path] [--debug]

ROOT_DIR=""
LIMIT=20
SHOW_FULL_PATH=false
DEBUG=false

usage() {
  warning "Usage: $0 --path=/path/to/tv [--limit=20] [--full-path] [--debug]"
}

debug() {
  if [[ "$DEBUG" == true ]]; then
    note "[DEBUG] $1"
  fi
}

is_tv_show_folder() {
  local dir="$1"

  debug "Checking folder: $dir"

  # Use process substitution instead of a pipe so return works correctly.
  # A pipe would run the loop in a subshell and break early returns.
  while IFS= read -r subdir; do
    local subdir_name
    subdir_name="$(basename "$subdir")"

    debug "  Found child folder: $subdir_name"

    if [[ "$subdir_name" =~ ^Season[[:space:]]+[0-9]+$ ]]; then
      debug "  Matched season folder in: $dir"
      return 0
    fi
  done < <(find "$dir" -mindepth 1 -maxdepth 1 -type d 2>/dev/null)

  debug "  No season folders found in: $dir"
  return 1
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --path=*)
      ROOT_DIR="${1#*=}"
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
    --debug)
      DEBUG=true
      shift
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    *)
      warning "Unknown argument: $1"
      usage
      exit 1
      ;;
  esac
done

note "Searching in: $ROOT_DIR"
note "Limit: ${LIMIT}"
note "Show full path: ${SHOW_FULL_PATH}"
note "Debug: ${DEBUG}"

if [[ -z "$ROOT_DIR" ]]; then
  usage
  exit 1
fi

if [[ ! -d "$ROOT_DIR" ]]; then
  warning "Error: '$ROOT_DIR' is not a valid directory"
  exit 1
fi

if ! [[ "$LIMIT" =~ ^[0-9]+$ ]] || [[ "$LIMIT" -lt 1 ]]; then
  warning "Error: --limit must be a positive integer"
  exit 1
fi

tmp_file="$(mktemp)"
trap 'rm -f "$tmp_file"' EXIT

note "Scanning for TV show folders..."

show_count=0

while IFS= read -r dir; do
  debug "Scanning candidate: $dir"

  if is_tv_show_folder "$dir"; then
    size_kb="$(du -sk "$dir" | awk '{print $1}')"
    show_name="$(basename "$dir")"
    debug "Detected TV show folder: $show_name | Size KB: $size_kb"
    printf "%s\t%s\t%s\n" "$size_kb" "$show_name" "$dir" >> "$tmp_file"
    ((show_count += 1))
  fi
done < <(find "$ROOT_DIR" -type d 2>/dev/null)

info "Detected $show_count TV show folder(s)"

if [[ ! -s "$tmp_file" ]]; then
  warning "No TV show folders found."
  exit 0
fi

note "Top $LIMIT largest TV show folders:"

sort -rn "$tmp_file" | head -n "$LIMIT" | while IFS=$'\t' read -r size_kb show_name show_dir; do
  size_bytes=$((size_kb * 1024))
  formatted_size="$(format_bytes "$size_bytes")"

  if [[ "$SHOW_FULL_PATH" == true ]]; then
    printf "%-12s %s\n" "$formatted_size" "$show_dir"
  else
    printf "%-12s %s\n" "$formatted_size" "$show_name"
  fi
done