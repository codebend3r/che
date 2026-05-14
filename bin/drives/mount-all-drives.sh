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

USE_IP=false
ONLY=""
QUIET=false
WAIT_TIMEOUT=15

usage() {
  cat <<EOF
Usage:
  $(basename "$0") [--only=NAME] [--use-ip] [--wait=SECONDS] [--quiet]

Description:
  💿 Mount all NAS drives via SMB. Already-mounted drives are skipped.
  Polls /Volumes for each mount to confirm it landed before moving on.

Options:
  --only=NAME      Only mount the drive with this name (case-insensitive)
  --use-ip         Mount via smb://IP instead of smb://NAME
  --wait=N         Seconds to wait for each mount to appear (default: ${WAIT_TIMEOUT})
  --quiet          Only log mounts and failures
  --help           Show help
EOF
}

for arg in "$@"; do
  case "$arg" in
    --only=*)    ONLY="${arg#*=}" ;;
    --use-ip)    USE_IP=true ;;
    --wait=*)    WAIT_TIMEOUT="${arg#*=}" ;;
    --quiet)     QUIET=true ;;
    --help|-h)   usage; exit 0 ;;
    *) warning "❌ Unknown argument: $arg"; usage; exit 1 ;;
  esac
done

if ! [[ "$WAIT_TIMEOUT" =~ ^[0-9]+$ ]] || [[ "$WAIT_TIMEOUT" -lt 1 ]]; then
  warning "❌ --wait must be a positive integer (got: ${WAIT_TIMEOUT})"
  exit 1
fi

lower() { printf '%s' "$1" | tr '[:upper:]' '[:lower:]'; }

note "═══════════════════════════════════════════"
note "💿  mount-all-drives"
note "═══════════════════════════════════════════"

mounted=0
skipped=0
failed=0

mount_drive() {
  local name="$1" ip="$2"
  local target
  if [[ "$USE_IP" == true ]]; then
    target="smb://$ip"
  else
    target="smb://$name"
  fi

  if [[ -d "/Volumes/$name" ]] || [[ -d "/Volumes/$ip" ]]; then
    [[ "$QUIET" == true ]] || info "⏭️  $name — already mounted"
    skipped=$((skipped + 1))
    return 0
  fi

  log "🔗 Mounting $name ($target)..."
  if ! open "$target" >/dev/null 2>&1; then
    warning "  ❌ Failed to invoke open for $target"
    failed=$((failed + 1))
    return 1
  fi

  local elapsed=0
  while [[ $elapsed -lt $WAIT_TIMEOUT ]]; do
    if [[ -d "/Volumes/$name" ]] || [[ -d "/Volumes/$ip" ]]; then
      success "  ✅ $name mounted 🐉"
      mounted=$((mounted + 1))
      return 0
    fi
    sleep 1
    elapsed=$((elapsed + 1))
  done

  warning "  ⏰ $name did not appear under /Volumes within ${WAIT_TIMEOUT}s"
  failed=$((failed + 1))
  return 1
}

for entry in "${drives[@]}"; do
  IFS="|" read -r driveName ip <<< "$entry"

  if [[ -n "$ONLY" ]] && [[ "$(lower "$driveName")" != "$(lower "$ONLY")" ]]; then
    continue
  fi

  mount_drive "$driveName" "$ip" || true
done

echo
note "─────────────────────────────────────────────"
success "✅ Mounted:  $mounted"
info    "⏭️  Skipped:  $skipped (already mounted)"
if [[ $failed -gt 0 ]]; then
  warning "❌ Failed:   $failed"
  exit 1
fi
log "🎉 All drives are up! 🐉🐉🐉"
