#!/usr/bin/env bash

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
. "$SCRIPT_DIR/../utils.sh" --source-only

set -euo pipefail

# v3.0.0

# name|ip
drives=(
  "Meleys|192.168.50.2"
  "Vermithor|192.168.50.3"
  "Caraxes|192.168.50.4"
  "Syrax|192.168.50.5"
  "Vhagar|192.168.50.6"
)

DRY_RUN=false
ONLY=""
QUIET=false
FORCE=true

usage() {
  cat <<EOF
Usage:
  $(basename "$0") [--dry-run] [--only=NAME] [--no-force] [--quiet]

Description:
  📤 Eject all NAS volumes from /Volumes. Checks for the primary mount
  as well as duplicate "<name>-1" and IP-named mounts that show up when
  macOS re-mounts the same share twice. Stale placeholder dirs left by
  force-unmount are cleaned up via rmdir (sudo as a fallback).

Options:
  --dry-run        Show what would be unmounted, change nothing
  --only=NAME      Only eject the drive with this name (case-insensitive)
  --no-force       Use 'diskutil unmount' instead of 'diskutil unmount force'
  --quiet          Only log unmounts and failures
  --help           Show help
EOF
}

for arg in "$@"; do
  case "$arg" in
    --dry-run)   DRY_RUN=true ;;
    --only=*)    ONLY="${arg#*=}" ;;
    --no-force)  FORCE=false ;;
    --quiet)     QUIET=true ;;
    --help|-h)   usage; exit 0 ;;
    *) warning "❌ Unknown argument: $arg"; usage; exit 1 ;;
  esac
done

lower() { printf '%s' "$1" | tr '[:upper:]' '[:lower:]'; }

header_suffix=""
[[ "$DRY_RUN" == true ]] && header_suffix=" 🌵 (dry run)"

note "═══════════════════════════════════════════"
note "📤  eject-all-drives${header_suffix}"
note "═══════════════════════════════════════════"

ejected=0
skipped=0
failed=0

eject_volume() {
  local label="$1"
  local mount="/Volumes/$label"

  if [[ ! -d "$mount" ]]; then
    [[ "$QUIET" == true ]] || info "  ⏭️  $label — not mounted"
    skipped=$((skipped + 1))
    return 0
  fi

  if [[ "$DRY_RUN" == true ]]; then
    warning "  🪄 Would unmount $mount"
    ejected=$((ejected + 1))
    return 0
  fi

  local unmount_cmd=(diskutil unmount)
  [[ "$FORCE" == true ]] && unmount_cmd=(diskutil unmount force)

  log "  📤 Unmounting $mount..."
  if "${unmount_cmd[@]}" "$mount" >/dev/null 2>&1; then
    if [[ -d "$mount" ]]; then
      rmdir "$mount" 2>/dev/null || sudo rmdir "$mount" 2>/dev/null || true
    fi
    success "  ✅ $label ejected"
    ejected=$((ejected + 1))
  else
    warning "  ❌ Failed to unmount $mount"
    failed=$((failed + 1))
  fi
}

for entry in "${drives[@]}"; do
  IFS="|" read -r driveName ip <<< "$entry"

  if [[ -n "$ONLY" ]] && [[ "$(lower "$driveName")" != "$(lower "$ONLY")" ]]; then
    continue
  fi

  info "🐉 ${driveName} (${ip})"
  eject_volume "$driveName"
  eject_volume "${driveName}-1"
  eject_volume "$ip"
done

echo
note "─────────────────────────────────────────────"
if [[ "$DRY_RUN" == true ]]; then
  success "🌵 Would eject:  $ejected"
  info    "⏭️  Skipped:     $skipped (not mounted)"
  log "💡 Dry run complete. Nothing was actually ejected."
else
  success "✅ Ejected:  $ejected"
  info    "⏭️  Skipped:  $skipped (not mounted)"
  if [[ $failed -gt 0 ]]; then
    warning "❌ Failed:   $failed"
    exit 1
  fi
  log "🎉 All clean! 🧹✨"
fi
