#!/usr/bin/env bash

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
. "$SCRIPT_DIR/../utils.sh" --source-only

set -euo pipefail

# v3.0.0

usage() {
  cat <<EOF
Usage:
  $(basename "$0") [--author=EMAIL] [--limit=N]

Description:
  🌿 Check out the most recent N remote branches authored by EMAIL
  that aren't yet present locally.

Options:
  --author=EMAIL   Author email to match (default: git config user.email)
  --limit=N        How many recent remote branches to scan (default: 100)
  --help           Show help
EOF
}

AUTHOR="$(git config user.email || true)"
LIMIT=100

# ⚙️  CLI — long flags only (see ../utils.sh).
while [[ $# -gt 0 ]]; do
  case "$1" in
    --author=*)
      AUTHOR="${1#*=}"
      shift
      ;;
    --limit=*)
      LIMIT="${1#*=}"
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

if [[ -z "$AUTHOR" ]]; then
  warning "❌ No author email — pass --author=EMAIL or set git config user.email"
  exit 1
fi

if ! [[ "$LIMIT" =~ ^[0-9]+$ ]] || [[ "$LIMIT" -lt 1 ]]; then
  warning "❌ --limit must be a positive integer (got: $LIMIT)"
  exit 1
fi

note "═══════════════════════════════════════════"
note "🌿  checkout-my-branches"
note "═══════════════════════════════════════════"

if [[ -n "$(git status --porcelain)" ]]; then
  warning "❌ Working tree is dirty. Commit or stash before running. 🧺"
  exit 1
fi

info "📡 Fetching remotes..."
git fetch --all --prune --quiet

info "📦 Scanning ${LIMIT} most recent remote branches for author 👤 ${AUTHOR}..."

checked_out=0
skipped=0
not_mine=0

# One pass: author email + refname + symref target. Newest first.
# %(symref) is non-empty for symbolic refs like origin/HEAD — we skip those.
while IFS='|' read -r author_email remote_branch symref; do
  [[ -z "$remote_branch" ]] && continue
  [[ -n "$symref" ]] && continue  # skip origin/HEAD and any other symbolic refs

  author_email="${author_email#<}"
  author_email="${author_email%>}"

  if [[ "$author_email" != "$AUTHOR" ]]; then
    not_mine=$((not_mine + 1))
    continue
  fi

  local_branch="${remote_branch#origin/}"
  if [[ -z "$local_branch" || "$local_branch" == "$remote_branch" ]]; then
    continue  # malformed entry — don't touch
  fi

  if git show-ref --verify --quiet "refs/heads/$local_branch"; then
    info "⏭️  Already local: $local_branch"
    skipped=$((skipped + 1))
  else
    log "🆕 Checking out: $local_branch"
    git checkout -b "$local_branch" --track "$remote_branch"
    checked_out=$((checked_out + 1))
  fi
done < <(
  git for-each-ref \
    --sort=-committerdate \
    --format='%(authoremail)|%(refname:short)|%(symref)' \
    refs/remotes/origin \
  | head -n "$LIMIT"
)

echo
success "═══ summary ═══"
success "🆕  Checked out: ${checked_out}"
success "⏭️  Already local: ${skipped}"
success "👻  Skipped (not yours): ${not_mine}"
success "✨ Done."
