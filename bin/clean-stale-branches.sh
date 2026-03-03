#!/opt/homebrew/bin/bash

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
. "$SCRIPT_DIR/utils.sh" --source-only

info "--------------------------------"
info "clean stale branches"
info "--------------------------------"

# Defaults
DRY_RUN=false

# Argument parsing
while [[ $# -gt 0 ]]; do
  case "$1" in
    --dry-run)
      DRY_RUN=true
      shift
      ;;
    -h|--help)
      echo "Usage: $0 [--dry-run]"
      exit 0
      ;;
    *)
      warning "Unknown argument: $1"
      echo "Usage: $0 [--dry-run]"
      exit 1
      ;;
  esac
done

# Protected branches that should not be deleted
PROTECTED_BRANCHES=("main" "dev" "staging")

# Fetch all remotes
git fetch --all

wasCleaned=false

info "Checking for stale branches..."

# Loop through all local branches
for branch in $(git for-each-ref --format='%(refname:short)' refs/heads/); do
  # Skip protected branches
  if [[ " ${PROTECTED_BRANCHES[*]} " =~ " $branch " ]]; then
    continue
  fi

  info "branch: $branch"

  # Check if branch is stale (tracking remote gone)
  if git branch -vv | grep -E "\[origin/${branch//\//\\/}: gone\]" > /dev/null; then
    if [[ "$DRY_RUN" == true ]]; then
      warning "Would delete stale branch: $branch"
    else
      warning "Deleting stale branch: $branch"
      git branch -D "$branch"
    fi
    wasCleaned=true
  fi
done

if [[ $wasCleaned == false ]]; then
  log "No stale branches were removed"
elif [[ "$DRY_RUN" == true ]]; then
  log "Dry run complete. No branches were actually deleted."
fi