#!/usr/bin/env bash

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=bin/utils.sh
. "$SCRIPT_DIR/../utils.sh" --source-only

set -euo pipefail

# v1.0.0

DRY_RUN=false
DO_CASK=true
DO_CLEANUP=true
DO_AUTOREMOVE=true
GREEDY=false
DOCTOR=false

usage() {
  cat <<EOF
Usage:
  $(basename "$0") [--dry-run] [--no-cask] [--no-cleanup] [--no-autoremove] [--greedy] [--doctor]

Description:
  🍺 Update Homebrew itself, upgrade all installed formulae and casks,
  then clean up old versions and prune unused dependencies.

Options:
  --dry-run        Show what would be upgraded/removed, change nothing
  --no-cask        Skip upgrading casks (apps)
  --no-cleanup     Skip 'brew cleanup' at the end
  --no-autoremove  Skip 'brew autoremove' (leave unused deps in place)
  --greedy         Pass --greedy to cask upgrade (force-update apps that self-update)
  --doctor         Run 'brew doctor' at the very end
  --help           Show help
EOF
}

# ⚙️  CLI — long flags only (see ../utils.sh).

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
    --no-cask)
      DO_CASK=false
      shift
      ;;
    --no-cleanup)
      DO_CLEANUP=false
      shift
      ;;
    --no-autoremove)
      DO_AUTOREMOVE=false
      shift
      ;;
    --greedy)
      GREEDY=true
      shift
      ;;
    --doctor)
      DOCTOR=true
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

if ! command -v brew >/dev/null 2>&1; then
  warning "❌ 'brew' is not installed or not in PATH. Install Homebrew first: https://brew.sh"
  exit 1
fi

header_suffix=""
[[ "$DRY_RUN" == true ]] && header_suffix=" 🌵 (dry run)"

note "═══════════════════════════════════════════"
note "🍺  update-brew${header_suffix}"
note "═══════════════════════════════════════════"

run() {
  if [[ "$DRY_RUN" == true ]]; then
    warning "  🪄 Would run: $*"
  else
    log "  ▶ $*"
    "$@"
  fi
}

# 1. Refresh Homebrew itself and tap metadata
info "📡 Updating Homebrew metadata..."
run brew update

# 2. Upgrade formulae
info "⬆️  Upgrading formulae..."
if [[ "$DRY_RUN" == true ]]; then
  brew upgrade --dry-run || true
else
  brew upgrade
fi

# 3. Upgrade casks (apps)
if [[ "$DO_CASK" == true ]]; then
  info "📦 Upgrading casks..."
  cask_args=(--cask)
  [[ "$GREEDY" == true ]] && cask_args+=(--greedy)
  if [[ "$DRY_RUN" == true ]]; then
    brew upgrade "${cask_args[@]}" --dry-run || true
  else
    brew upgrade "${cask_args[@]}"
  fi
else
  note "⏭️  Skipping cask upgrades (--no-cask)"
fi

# 4. Remove unused dependencies
if [[ "$DO_AUTOREMOVE" == true ]]; then
  info "🧹 Removing unused dependencies..."
  if [[ "$DRY_RUN" == true ]]; then
    brew autoremove --dry-run || true
  else
    brew autoremove
  fi
else
  note "⏭️  Skipping autoremove (--no-autoremove)"
fi

# 5. Cleanup old versions + cache
if [[ "$DO_CLEANUP" == true ]]; then
  info "🗑️  Cleaning up old versions and cache..."
  if [[ "$DRY_RUN" == true ]]; then
    brew cleanup --dry-run -s || true
  else
    brew cleanup -s
  fi
else
  note "⏭️  Skipping cleanup (--no-cleanup)"
fi

# 6. Optional doctor pass
if [[ "$DOCTOR" == true ]]; then
  info "🩺 Running brew doctor..."
  brew doctor || warning "⚠️  brew doctor reported issues (non-fatal)"
fi

echo
note "─────────────────────────────────────────────"
if [[ "$DRY_RUN" == true ]]; then
  log "💡 Dry run complete. Nothing was actually changed."
else
  success "🎉 Homebrew is up to date and tidy! 🍺✨"
fi
