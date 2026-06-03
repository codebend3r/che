#!/usr/bin/env bash

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=bin/utils.sh
. "$SCRIPT_DIR/../utils.sh" --source-only

set -euo pipefail

# v3.0.0

# Usage:
#   compress-folders --path=/dir [--dry-run] [--verbose]

ROOT_DIR=""
DRY_RUN=false
VERBOSE=false

usage() {
  cat <<EOF
Usage:
  $(basename "$0") --path=/dir [--dry-run] [--verbose]

Description:
  📦 Create a max-compression .zip of every immediate subfolder of --path.
  Each "<folder>" becomes "<folder>.zip" alongside it. Existing archives
  are cleanly replaced (zip -FS sync), not appended to.

Options:
  --path=DIR    Parent directory whose subfolders should be zipped (required)
  --dry-run     Print what would be zipped, change nothing
  --verbose     Show zip's per-file progress
  --help        Show help
EOF
}

# ⚙️  CLI — long flags only (see ../utils.sh).
while [[ $# -gt 0 ]]; do
  case "$1" in
    --path=*)
      ROOT_DIR="${1#*=}"
      shift
      ;;
    --dry-run=*)
      DRY_RUN="${1#*=}"
      shift
      ;;
    --dry-run)
      DRY_RUN=true
      shift
      ;;
    --verbose=*)
      VERBOSE="${1#*=}"
      shift
      ;;
    --verbose)
      VERBOSE=true
      shift
      ;;
    --help|-h)
      usage
      exit 0
      ;;
    *)
      warning "❌ Unknown argument: $1"
      usage
      exit 1
      ;;
  esac
done

if [[ -z "$ROOT_DIR" ]]; then
  warning "❌ --path is required"
  usage
  exit 1
fi

if [[ ! -d "$ROOT_DIR" ]]; then
  warning "❌ Directory not found: $ROOT_DIR"
  exit 1
fi

if ! command -v zip >/dev/null 2>&1; then
  warning "❌ 'zip' is not installed or not in PATH."
  exit 1
fi

ROOT_DIR="${ROOT_DIR%/}"

header_suffix=""
[[ "$DRY_RUN" == true ]] && header_suffix=" 🌵 (dry run)"

note "═══════════════════════════════════════════"
note "📦  compress-folders${header_suffix}"
note "═══════════════════════════════════════════"
note "Parent: $ROOT_DIR"

compressed=0
skipped=0

# nullglob so an empty parent doesn't iterate the literal "$ROOT_DIR/*/".
shopt -s nullglob
for dir in "$ROOT_DIR"/*/; do
  folder_path="${dir%/}"
  folder_name="$(basename "$folder_path")"
  zip_path="${folder_path}.zip"

  if [[ "$DRY_RUN" == true ]]; then
    info "  🪄 Would zip: $folder_name → ${folder_name}.zip"
    compressed=$((compressed + 1))
    continue
  fi

  info "📦 Compressing '$folder_name'..."

  zip_args=(-r -9 -FS)
  [[ "$VERBOSE" != true ]] && zip_args+=(-q)

  # Run from inside ROOT_DIR so the archive stores plain relative paths
  # (./folder/...) instead of the absolute path the user passed in.
  if ( cd "$ROOT_DIR" && zip "${zip_args[@]}" "${folder_name}.zip" "$folder_name" ); then
    success "  ✅ ${folder_name}.zip"
    compressed=$((compressed + 1))
  else
    warning "  ❌ Failed: $zip_path"
    skipped=$((skipped + 1))
  fi
done
shopt -u nullglob

echo
note "─────────────────────────────────────────────"
if [[ "$DRY_RUN" == true ]]; then
  success "🌵 Would compress: $compressed folder(s)"
  log "💡 Dry run complete. Nothing was actually changed."
else
  success "✅ Compressed: $compressed"
  if [[ $skipped -gt 0 ]]; then
    warning "❌ Failed:     $skipped"
    exit 1
  fi
  log "🎉 Compression complete."
fi
