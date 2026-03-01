#!/opt/homebrew/bin/bash

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
. "$SCRIPT_DIR/utils.sh" --source-only

set -euo pipefail

# v2.0.3

# Author to filter
TARGET_EMAIL="cj.rivas.dev@gmail.com"

# Get the current branch to return to it later
ORIGINAL_BRANCH=$(git branch --show-current)

# Fetch all remotes
git fetch --all --quiet

info "🧹 Deleting branches whose upstream is gone..."

git branch -vv | while read -r line; do
  # First column is the branch; may be prefixed with '*'
  branch=$(echo "$line" | awk '{print $1}')
  branch=${branch#\*}  # strip leading '*' if present

  # Skip empty (paranoia)
  [[ -z "$branch" ]] && continue

  # Skip current branch just in case
  if [[ "$branch" == "$ORIGINAL_BRANCH" ]]; then
    continue
  fi

  # Detect "gone" status:
  #   - Some formats: [origin/CON-695-main: gone]
  #   - Others:       [gone]
  if [[ "$line" == *"[gone]"* || "$line" == *": gone]"* ]]; then
    warning "⚠️  Deleting local branch '$branch' (upstream gone)"
    git branch -D "$branch"
  fi
done

# info "📦 Gathering latest commit dates of all remote branches..."

# branch_info=$(for branch in $(git branch -r | grep -v '\->'); do
#   latest_commit=$(git log -1 --pretty=format:"%H" "$branch")
#   commit_date=$(git show -s --format="%ct" "$latest_commit") # Unix timestamp
#   echo "$commit_date $branch"
# done)

# latest_100=$(echo "$branch_info" | sort -nr | head -n 100 | awk '{print $2}')

# info "🔍 Filtering for branches created by $TARGET_EMAIL..."

# while read -r remote_branch; do
#   latest_commit=$(git log -1 --pretty=format:"%H" "$remote_branch")
#   author_email=$(git show -s --format="%ae" "$latest_commit")

#   if [[ "$author_email" == "$TARGET_EMAIL" ]]; then
#     local_branch=${remote_branch#origin/}

#     log "✅ $remote_branch created by $author_email"

#     if git show-ref --verify --quiet "refs/heads/$local_branch"; then
#       info "⏭️  Local branch '$local_branch' already exists. Skipping."
#     else
#       git checkout -b "$local_branch" --track "$remote_branch"
#     fi
#   fi
# done <<< "$latest_100"

# Return to original branch
info "🔁 Returning to original branch: $ORIGINAL_BRANCH"
git checkout "$ORIGINAL_BRANCH"