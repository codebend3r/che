#!/usr/bin/env bash

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=bin/utils.sh
. "$SCRIPT_DIR/../utils.sh" --source-only

set -euo pipefail

# v3.3.0

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
CLEAR_FAVORITES=true

usage() {
  cat <<EOF
Usage:
  $(basename "$0") [--dry-run] [--only=NAME] [--no-force] [--no-clear-favorites] [--quiet]

Description:
  📤 Eject all NAS volumes from /Volumes. Checks for the primary mount
  as well as duplicate "<name>-1" and IP-named mounts that show up when
  macOS re-mounts the same share twice. Stale placeholder dirs left by
  force-unmount are cleaned up via rmdir (sudo as a fallback).

  Also resets Finder's Favorite Servers + Recent Hosts lists, otherwise
  ejected NAS shares keep reappearing in the sidebar Locations after
  Finder relaunches.

Options:
  --dry-run              Show what would be unmounted, change nothing
  --only=NAME            Only eject the drive with this name (case-insensitive);
                         skips the Favorite Servers reset (would be over-broad)
  --no-force             Use 'diskutil unmount' instead of 'diskutil unmount force'
  --no-clear-favorites   Don't reset Finder's Favorite Servers / Recent Hosts lists
  --quiet                Only log unmounts and failures
  --help                 Show help
EOF
}

# ⚙️  CLI — long flags only; `--dry-run` optionally `--dry-run=true|false` (see ../utils.sh).

while [[ $# -gt 0 ]]; do
  case "$1" in
    --dry-run=*)
      DRY_RUN="${1#*=}"
      shift
      ;;
    --dry-run)
      DRY_RUN=true
      shift
      ;;
    --only=*)
      ONLY="${1#*=}"
      shift
      ;;
    --no-force)
      FORCE=false
      shift
      ;;
    --no-clear-favorites)
      CLEAR_FAVORITES=false
      shift
      ;;
    --quiet)
      QUIET=true
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
  log "🪪 Asking Finder to drop any server-level entries..."
  for entry in "${drives[@]}"; do
    IFS="|" read -r driveName ip <<< "$entry"
    if [[ -n "$ONLY" ]] && [[ "$(lower "$driveName")" != "$(lower "$ONLY")" ]]; then
      continue
    fi
    osascript -e "tell application \"Finder\" to try" \
              -e "eject disk \"$driveName\"" \
              -e "end try" >/dev/null 2>&1 || true
  done

  # Reset Finder's Favorite Servers + Recent Hosts lists. Without this,
  # the smb://<name> entries auto-populate the sidebar Locations on the
  # next Finder launch even though nothing is mounted. Skipped when
  # --only is set (would nuke the other drives' favorites too).
  if [[ -z "$ONLY" ]] && [[ "$CLEAR_FAVORITES" == true ]]; then
    log "🧽 Resetting Finder Favorite Servers + Recent Hosts lists..."
    sfltool resetlist com.apple.LSSharedFileList.FavoriteServers >/dev/null 2>&1 || true
    sfltool resetlist com.apple.LSSharedFileList.RecentHosts >/dev/null 2>&1 || true
  fi

  # Hard-kill (SIGKILL) so Finder cannot save its current sidebar state on
  # the way out — otherwise it restores stale server entries on relaunch.
  log "🔄 Hard-killing Finder so it doesn't restore stale sidebar state..."
  killall -KILL Finder 2>/dev/null || true
  log "🎉 All clean! 🧹✨"
fi
