#!/usr/bin/env bash

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=bin/utils.sh
. "$SCRIPT_DIR/../utils.sh" --source-only

set -euo pipefail

# v4.1.0

SMB_USER="crivas"

# name|ip  (share name is assumed to match the drive name)
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

usage() {
  cat <<EOF
Usage:
  $(basename "$0") [--only=NAME] [--use-ip] [--quiet]

Description:
  💿 Mount all NAS drives via SMB using AppleScript's 'mount volume'
  (no Finder modals; same NetAuth path Finder uses, so /Volumes/<name>
  is created automatically and Keychain credentials are used silently).
  Reads credentials from Keychain for user '${SMB_USER}'. Already-mounted
  drives are skipped. The share name is assumed to match the drive name
  (e.g. //${SMB_USER}@Meleys/Meleys → /Volumes/Meleys).

Options:
  --only=NAME      Only mount the drive with this name (case-insensitive)
  --use-ip         Mount via //${SMB_USER}@IP/NAME instead of //${SMB_USER}@NAME/NAME
  --quiet          Only log mounts and failures
  --help           Show help
EOF
}

# ⚙️  CLI — long flags only (see ../utils.sh).

while [[ $# -gt 0 ]]; do
  case "$1" in
    --only=*)
      ONLY="${1#*=}"
      shift
      ;;
    --use-ip)
      USE_IP=true
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

# True iff something is currently mounted at /Volumes/<name>
is_mounted() {
  mount | grep -q " on /Volumes/$1 ("
}

note "═══════════════════════════════════════════"
note "💿  mount-all-drives"
note "═══════════════════════════════════════════"

mounted=0
skipped=0
failed=0

mount_drive() {
  local name="$1"
  local ip="$2"
  local host url err

  if is_mounted "$name"; then
    [[ "$QUIET" == true ]] || info "⏭️  $name — already mounted"
    skipped=$((skipped + 1))
    return 0
  fi

  if [[ "$USE_IP" == true ]]; then
    host="$ip"
  else
    host="$name"
  fi
  url="smb://${SMB_USER}@${host}/${name}"

  log "🔗 Mounting $name ($url)..."
  if err="$(osascript -e "mount volume \"$url\"" 2>&1 >/dev/null)"; then
    success "  ✅ $name mounted 🐉"
    mounted=$((mounted + 1))
    return 0
  fi

  warning "  ❌ mount failed for $url"
  [[ -n "$err" ]] && warning "     ${err}"
  warning "     Check that Keychain has a password for '${SMB_USER}@${host}'."
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
