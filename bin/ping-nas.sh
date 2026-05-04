#!/bin/bash

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
. "$SCRIPT_DIR/utils.sh" --source-only

drives=(
  "smb://Meleys|smb://192.168.50.2"
  "smb://Vermithor|smb://192.168.50.3"
  "smb://Caraxes|smb://192.168.50.4"
  "smb://Syrax|smb://192.168.50.5"
  "smb://Vhagar|smb://192.168.50.6"
)

ping_all_nas() {
  log "🔄 Pinging all NAS drives to keep them awake..."
  for entry in "${drives[@]}"; do
    IFS="|" read -r driveName address <<< "$entry"
    ip="${address#smb://}"
    log "Pinging ${driveName} (${ip})"
    ping -c 1 "${ip}" >/dev/null 2>&1 || log "⚠️ Ping failed: ${driveName}"
  done
}

info "🚀 Starting keep-alive pinger for all 5 NAS (every 5 min)..."

while true; do
  ping_all_nas
  sleep 300
done