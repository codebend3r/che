#!/usr/bin/env bash

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
. "$SCRIPT_DIR/utils.sh" --source-only

set -euo pipefail

# v2.0.0

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

usage() {
  cat <<EOF
Usage:
  $(basename "$0") [--interval=SECONDS] [--once] [--quiet]

Description:
  Keep-alive pinger for the NAS drives. Runs forever by default,
  pinging each host once per cycle.

Options:
  --interval=N    Seconds between cycles (default: ${INTERVAL})
  --once          Run a single cycle and exit (useful from cron)
  --quiet         Only log failures and the final summary
  --help          Show help
EOF
}

for arg in "$@"; do
  case "$arg" in
    --interval=*) INTERVAL="${arg#*=}" ;;
    --once) ONCE=true ;;
    --quiet) QUIET=true ;;
    --help|-h) usage; exit 0 ;;
    *) warning "Unknown argument: $arg"; usage; exit 1 ;;
  esac
done

if ! [[ "$INTERVAL" =~ ^[0-9]+$ ]] || [[ "$INTERVAL" -lt 1 ]]; then
  warning "--interval must be a positive integer (got: ${INTERVAL})"
  exit 1
fi

ping_all_nas() {
  local failed=0
  [[ "$QUIET" == "true" ]] || log "🔄 Pinging ${#drives[@]} NAS drives to keep them awake..."

  for entry in "${drives[@]}"; do
    IFS="|" read -r driveName ip <<< "$entry"
    if ping -c 1 -t "$PING_TIMEOUT" "$ip" >/dev/null 2>&1; then
      [[ "$QUIET" == "true" ]] || log "  ✓ ${driveName} (${ip})"
    else
      warning "  ✗ ${driveName} (${ip}) — ping failed"
      failed=$((failed + 1))
    fi
  done

  if [[ "$failed" -gt 0 ]]; then
    warning "${failed}/${#drives[@]} drive(s) unreachable"
  fi
}

shutdown() {
  echo
  info "👋 Stopping keep-alive pinger."
  exit 0
}
trap shutdown INT TERM

if [[ "$ONCE" == "true" ]]; then
  ping_all_nas
  exit 0
fi

info "🚀 Starting keep-alive pinger for ${#drives[@]} NAS (every ${INTERVAL}s). Ctrl-C to stop."

while true; do
  ping_all_nas
  sleep "$INTERVAL"
done
