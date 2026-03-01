#!/opt/homebrew/bin/bash

. ~/bin/utils.sh --source-only

set -euo pipefail

# v3.2.0

info "Running command in $(pwd)"

# Usage:
#   delete-duplicate-videos --path=./ [--dry-run] [--verbose]

DRY_RUN=false
VERBOSE=false
ROOT_DIR=""
DELETED_COUNT=0
SCANNED_COUNT=0

# Human-readable size helper
format_bytes() {
  local bytes=$1
  if [[ $bytes -ge 1073741824 ]]; then
    echo "$(echo "scale=2; $bytes/1073741824" | bc) GB"
  elif [[ $bytes -ge 1048576 ]]; then
    echo "$(echo "scale=2; $bytes/1048576" | bc) MB"
  elif [[ $bytes -ge 1024 ]]; then
    echo "$(echo "scale=2; $bytes/1024" | bc) KB"
  else
    echo "${bytes} B"
  fi
}

# SxxEyy where episode allows 2–3 digits
EP_REGEX='[Ss][0-9]{2}[Ee][0-9]{2,3}'

while [[ $# -gt 0 ]]; do
  case "$1" in
    --path=*)
      ROOT_DIR="${1#*=}"
      shift
      ;;
    --dry-run)
      DRY_RUN=true
      shift
      ;;
    --verbose)
      VERBOSE=true
      shift
      ;;
    -h|--help)
      echo "Usage: $0 --path=/path/to/media [--dry-run] [--verbose]"
      exit 0
      ;;
    *)
      warning "Unknown argument: $1"
      echo "Usage: $0 --path=/path/to/media [--dry-run] [--verbose]"
      exit 1
      ;;
  esac
done

log "ROOT_DIR: ${ROOT_DIR}"
log "DRY_RUN: ${DRY_RUN}"
log "VERBOSE: ${VERBOSE}"

[[ -z "$ROOT_DIR" ]] && { warning "Missing required argument: --path"; exit 1; }
[[ ! -d "$ROOT_DIR" ]] && { warning "The provided path '$ROOT_DIR' is not a valid directory."; exit 1; }

$DRY_RUN && info "Running in DRY-RUN mode — no files will be deleted."
$VERBOSE && info "Running in VERBOSE mode — more information will be displayed."

# Temporary file to hold: dir|token|filepath
TMPFILE=$(mktemp)
trap '[[ -n "$TMPFILE" && -f "$TMPFILE" ]] && rm -f "$TMPFILE"' EXIT

# 1) Collect all candidate files with their grouping key
while IFS= read -r -d '' file; do
  ((SCANNED_COUNT++))
  $VERBOSE && info "SCANNING: $file"

  name=$(basename "$file")

  if [[ $name =~ $EP_REGEX ]]; then
    base_token="${BASH_REMATCH[0]}"
  else
    continue
  fi

  dir=$(dirname "$file")
  printf '%s|%s|%s\n' "$dir" "$base_token" "$file" >> "$TMPFILE"
done < <(find "$ROOT_DIR" \( -iname "*.mkv" -o -iname "*.mp4" \) -type f -print0)

# Sort by dir+token so duplicates are adjacent
sort "$TMPFILE" -o "$TMPFILE"

process_group() {
  # $@ = list of file paths in this group
  local files=("$@")
  local count=${#files[@]}

  [[ $count -le 1 ]] && return

  local size_file_list=()
  local f size

  for f in "${files[@]}"; do
    [[ -f "$f" ]] || continue
    size=$(stat -f %z "$f")
    size_file_list+=("${size}:${f}")
  done

  [[ ${#size_file_list[@]} -le 1 ]] && return

  # Sort by size descending
  local sorted_list
  sorted_list=$(printf "%s\n" "${size_file_list[@]}" | sort -nr)

  # Convert sorted list into array
  local sorted_lines=()
  IFS=$'\n' read -r -a sorted_lines <<< "$sorted_list"

  # Keep largest (index 0)
  if [[ ${#sorted_lines[@]} -gt 0 ]]; then
    local line size_keep file_keep
    line="${sorted_lines[0]}"
    size_keep="${line%%:*}"
    file_keep="${line#*:}"
    $VERBOSE && info "KEEPING: $file_keep ($(format_bytes "$size_keep"))"
  fi

  # Delete all others
  local i line size_del file_del size_human
  for (( i = 1; i < ${#sorted_lines[@]}; i++ )); do
    line="${sorted_lines[$i]}"
    size_del="${line%%:*}"
    file_del="${line#*:}"
    size_human=$(format_bytes "$size_del")

    if [[ "$file_del" =~ \.srt$ ]]; then
      $VERBOSE && info "SKIP: $file_del (subtitle file)"
      continue
    fi

    if $DRY_RUN; then
      ((DELETED_COUNT++))
      warning "[DRY-RUN] ❌ Would delete: $file_del ($size_human)"
    else
      warning "❌ Deleting: $file_del ($size_human)"
      if rm -f "$file_del"; then
        ((DELETED_COUNT++))
      fi
    fi
  done
}

# 2) Walk sorted file and process each group
current_key=""
matches=()

while IFS='|' read -r dir token filepath; do
  key="${dir}|${token}"

  if [[ "$key" != "$current_key" && ${#matches[@]} -gt 0 ]]; then
    process_group "${matches[@]}"
    matches=()
  fi

  current_key="$key"
  matches+=("$filepath")
done < "$TMPFILE"

# Last group
if [[ ${#matches[@]} -gt 0 ]]; then
  process_group "${matches[@]}"
fi

if ! $DRY_RUN; then
  log "Total files deleted: $DELETED_COUNT"
else
  log "Total files that *would* be deleted: $DELETED_COUNT"
fi

log "Total files scanned: $SCANNED_COUNT"
log "Scanning complete."