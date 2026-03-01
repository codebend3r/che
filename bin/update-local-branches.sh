#!/opt/homebrew/bin/bash

. ~/bin/utils.sh --source-only

info "--------------------------------"
info "update local branches"
info "--------------------------------"

# Get the current branch to return to it later
ORIGINAL_BRANCH=$(git branch --show-current)

# Fetch all remotes
git fetch --all --quiet

# Loop through all local branches
for branch in $(git branch --format='%(refname:short)'); do
  info "Checking out branch: $branch"

  git checkout "$branch"
  git status "$branch"

  # Check if the branch has an upstream tracking branch
  upstream=$(git rev-parse --abbrev-ref --symbolic-full-name @{u} 2>/dev/null)

  if [[ -n "$upstream" ]]; then
    info "Upstream found for: $branch: $upstream"

    # Pull the latest changes with rebase
    if git pull --rebase; then
      log "Successfully pulled latest changes for: $branch"
    else
      warning "Failed to pull changes for: $branch. You may need to resolve conflicts."
      exit 1  # Exit if rebase fails
    fi
  else
    info "No upstream found for branch: $branch. Skipping pull."
  fi
done

# Return to original branch
info "🔁 Returning to original branch: $ORIGINAL_BRANCH"
git checkout "$ORIGINAL_BRANCH"
