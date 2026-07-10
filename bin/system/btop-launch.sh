#!/usr/bin/env bash

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=bin/utils.sh
. "$SCRIPT_DIR/../utils.sh" --source-only

set -euo pipefail

# v1.0.0

# 🖥️  Launch btop with a gruvbox theme that follows the macOS appearance.
# Light mode -> gruvbox_light, Dark mode -> gruvbox_dark_v2. The chosen theme
# is written into btop.conf before launch (btop reads its config once at start).

CONF="${HOME}/.config/btop/btop.conf"
LIGHT_THEME="gruvbox_light"
DARK_THEME="gruvbox_dark_v2"

usage() {
  cat <<EOF
Usage:
  $(basename "$0") [btop-args...]

Description:
  🖥️  Set btop's color_theme to match the current macOS appearance
  (${LIGHT_THEME} in Light mode, ${DARK_THEME} in Dark mode), then exec btop.
  Any extra arguments are passed straight through to btop.
EOF
}

case "${1:-}" in
  -h | --help)
    usage
    exit 0
    ;;
esac

# `defaults read -g AppleInterfaceStyle` prints "Dark" in Dark mode and exits
# non-zero (no key) in Light mode.
if [[ "$(defaults read -g AppleInterfaceStyle 2>/dev/null || true)" == "Dark" ]]; then
  THEME="$DARK_THEME"
else
  THEME="$LIGHT_THEME"
fi

if [[ -f "$CONF" ]]; then
  # Replace the existing color_theme line in place.
  perl -i -pe "s/^color_theme\s*=.*/color_theme = \"${THEME}\"/" "$CONF"
  info "btop theme -> ${THEME}"
else
  warning "btop config not found at ${CONF}; launching with existing theme"
fi

exec btop "$@"
