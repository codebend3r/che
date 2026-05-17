#!/usr/bin/env bash

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
. "$SCRIPT_DIR/../utils.sh" --source-only

set -euo pipefail

# v3.3.0

SMB_USER="crivas"

# name|ip  (share name is assumed to match the drive name)
drives=(
  "Meleys|192.168.50.2"
  "Vermithor|192.168.50.3"
  "Caraxes|192.168.50.4"
  "Syrax|192.168.50.5"
  "Vhagar|192.168.50.6"
)

INTERVAL=300
ONCE=false
QUIET=false
PING_TIMEOUT=2
ONLY=""
REMOUNT=true
USE_IP=false

usage() {
  cat <<EOF
Usage:
  $(basename "$0") [--interval=SECONDS] [--ping-timeout=SECONDS]
                   [--only=NAME] [--no-remount] [--use-ip]
                   [--once] [--quiet]

Description:
  📡 Keep-alive pinger for the NAS drives. Each cycle pings every host
  and verifies it's still mounted under /Volumes. If a drive is reachable
  but the share has dropped off /Volumes (eject, network blip, sleep),
  it is silently remounted via AppleScript's 'mount volume' as user
  '${SMB_USER}' using Keychain credentials — no Finder modals.

Options:
  --interval=N       Seconds between cycles (default: ${INTERVAL})
  --ping-timeout=N   Per-host ping timeout in seconds (default: ${PING_TIMEOUT})
  --only=NAME        Only ping the drive with this name (case-insensitive)
  --no-remount       Detect-only: warn about missing mounts, don't remount
  --use-ip           Remount via //${SMB_USER}@IP/NAME instead of //${SMB_USER}@NAME/NAME
  --once             Run a single cycle and exit (useful from cron)
  --quiet            Only log failures, remount attempts, and cycle summary
  --help             Show help
EOF
}

# ⚙️  CLI — long flags only; boolean toggles never take a trailing `=`
#     unless noted in usage below (see ../utils.sh).

while [[ $# -gt 0 ]]; do
  case "$1" in
    --interval=*)
      INTERVAL="${1#*=}"
      shift
      ;;
    --ping-timeout=*)
      PING_TIMEOUT="${1#*=}"
      shift
      ;;
    --only=*)
      ONLY="${1#*=}"
      shift
      ;;
    --no-remount)
      REMOUNT=false
      shift
      ;;
    --use-ip)
      USE_IP=true
      shift
      ;;
    --once)
      ONCE=true
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

validate_positive_int() {
  local flag="$1" val="$2"
  if ! [[ "$val" =~ ^[0-9]+$ ]] || [[ "$val" -lt 1 ]]; then
    warning "❌ ${flag} must be a positive integer (got: ${val})"
    exit 1
  fi
}
validate_positive_int "--interval"     "$INTERVAL"
validate_positive_int "--ping-timeout" "$PING_TIMEOUT"

lower() { printf '%s' "$1" | tr '[:upper:]' '[:lower:]'; }

is_mounted() {
  mount | grep -q " on /Volumes/$1 ("
}

remount_drive() {
  local name="$1"
  local ip="$2"
  local host url err

  if [[ "$USE_IP" == true ]]; then
    host="$ip"
  else
    host="$name"
  fi
  url="smb://${SMB_USER}@${host}/${name}"

  log "  🔗 Remounting $name ($url)..."
  if err="$(osascript -e "mount volume \"$url\"" 2>&1 >/dev/null)"; then
    success "  ✅ $name remounted 🐉"
    return 0
  fi

  warning "  ❌ mount failed for $url"
  [[ -n "$err" ]] && warning "     ${err}"
  warning "     Check that Keychain has a password for '${SMB_USER}@${host}'."
  return 1
}

# Build the active drive list once (respecting --only)
active_drives=()
for entry in "${drives[@]}"; do
  IFS="|" read -r driveName _ <<< "$entry"
  if [[ -n "$ONLY" ]] && [[ "$(lower "$driveName")" != "$(lower "$ONLY")" ]]; then
    continue
  fi
  active_drives+=("$entry")
done

if [[ ${#active_drives[@]} -eq 0 ]]; then
  warning "❌ No drives matched --only=${ONLY}"
  exit 1
fi

cycle=0

ping_all_nas() {
  cycle=$((cycle + 1))
  local unreachable=0 unmounted=0 remounted=0 remount_failed=0

  [[ "$QUIET" == true ]] || log "🔄 Cycle #${cycle} — checking ${#active_drives[@]} NAS drive(s)..."

  for entry in "${active_drives[@]}"; do
    IFS="|" read -r driveName ip <<< "$entry"

    if ! ping -c 1 -t "$PING_TIMEOUT" "$ip" >/dev/null 2>&1; then
      warning "  ❌ ${driveName} (${ip}) — ping failed"
      unreachable=$((unreachable + 1))
      continue
    fi

    if is_mounted "$driveName"; then
      [[ "$QUIET" == true ]] || log "  ✅ 🐉 ${driveName} (${ip}) — mounted"
      continue
    fi

    warning "  ⚠️  ${driveName} (${ip}) — reachable but not mounted"
    unmounted=$((unmounted + 1))

    if [[ "$REMOUNT" == true ]]; then
      if remount_drive "$driveName" "$ip"; then
        remounted=$((remounted + 1))
      else
        remount_failed=$((remount_failed + 1))
      fi
    fi
  done

  local total=${#active_drives[@]}
  if [[ $unreachable -eq 0 && $unmounted -eq 0 ]]; then
    [[ "$QUIET" == true ]] || success "✨ All ${total} drive(s) responded and mounted 🎉"
  else
    local parts=()
    [[ $unreachable -gt 0 ]] && parts+=("${unreachable} unreachable")
    [[ $remounted -gt 0 ]] && parts+=("${remounted} remounted")
    [[ $remount_failed -gt 0 ]] && parts+=("${remount_failed} remount-failed")
    if [[ "$REMOUNT" == false && $unmounted -gt 0 ]]; then
      parts+=("${unmounted} unmounted")
    fi
    warning "⚠️  Cycle summary: ${parts[*]}"
  fi
}

shutdown() {
  echo
  info "👋 Stopping keep-alive pinger after ${cycle} cycle(s)."
  exit 0
}
trap shutdown INT TERM

note "═══════════════════════════════════════════"
note "📡  ping-nas"
note "═══════════════════════════════════════════"

if [[ "$ONCE" == true ]]; then
  ping_all_nas
  exit 0
fi

info "🚀 Keep-alive pinger started for ${#active_drives[@]} NAS (every ${INTERVAL}s). Press Ctrl-C to stop."

while true; do
  ping_all_nas
  sleep "$INTERVAL"
done
