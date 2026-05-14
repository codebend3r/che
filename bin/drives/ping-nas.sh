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

INTERVAL=300
ONCE=false
QUIET=false
PING_TIMEOUT=2
ONLY=""

usage() {
  cat <<EOF
Usage:
  $(basename "$0") [--interval=SECONDS] [--ping-timeout=SECONDS]
                   [--only=NAME] [--once] [--quiet]

Description:
  📡 Keep-alive pinger for the NAS drives. Runs forever by default,
  pinging each host once per cycle so the drives don't spin down.

Options:
  --interval=N       Seconds between cycles (default: ${INTERVAL})
  --ping-timeout=N   Per-host ping timeout in seconds (default: ${PING_TIMEOUT})
  --only=NAME        Only ping the drive with this name (case-insensitive)
  --once             Run a single cycle and exit (useful from cron)
  --quiet            Only log failures and the cycle summary
  --help             Show help
EOF
}

for arg in "$@"; do
  case "$arg" in
    --interval=*)     INTERVAL="${arg#*=}" ;;
    --ping-timeout=*) PING_TIMEOUT="${arg#*=}" ;;
    --only=*)         ONLY="${arg#*=}" ;;
    --once)           ONCE=true ;;
    --quiet)          QUIET=true ;;
    --help|-h)        usage; exit 0 ;;
    *) warning "❌ Unknown argument: $arg"; usage; exit 1 ;;
  esac
done

if ! [[ "$INTERVAL" =~ ^[0-9]+$ ]] || [[ "$INTERVAL" -lt 1 ]]; then
  warning "❌ --interval must be a positive integer (got: ${INTERVAL})"
  exit 1
fi

if ! [[ "$PING_TIMEOUT" =~ ^[0-9]+$ ]] || [[ "$PING_TIMEOUT" -lt 1 ]]; then
  warning "❌ --ping-timeout must be a positive integer (got: ${PING_TIMEOUT})"
  exit 1
fi

lower() { printf '%s' "$1" | tr '[:upper:]' '[:lower:]'; }

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
  local failed=0

  [[ "$QUIET" == true ]] || log "🔄 Cycle #${cycle} — pinging ${#active_drives[@]} NAS drive(s)..."

  for entry in "${active_drives[@]}"; do
    IFS="|" read -r driveName ip <<< "$entry"
    if ping -c 1 -t "$PING_TIMEOUT" "$ip" >/dev/null 2>&1; then
      [[ "$QUIET" == true ]] || log "  ✅ 🐉 ${driveName} (${ip})"
    else
      warning "  ❌ ${driveName} (${ip}) — ping failed"
      failed=$((failed + 1))
    fi
  done

  if [[ "$failed" -gt 0 ]]; then
    warning "⚠️  ${failed}/${#active_drives[@]} drive(s) unreachable"
  else
    [[ "$QUIET" == true ]] || success "✨ All ${#active_drives[@]} drive(s) responded 🎉"
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
