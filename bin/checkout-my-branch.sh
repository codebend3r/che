#!/opt/homebrew/bin/bash

. ~/bin/utils.sh --source-only

info "--------------------------------"
info "checkout my branches"
info "--------------------------------"

# Author to filter
TARGET_EMAIL="cj.rivas.dev@gmail.com"

# # Get the current branch to return to it later
# ORIGINAL_BRANCH=$(git branch --show-current)

# Fetch all remotes
git fetch --all --quiet

# Step 1: Get all remote branches with their latest commit date (timestamp)
info "📦 Gathering latest commit dates of all remote branches..."

branch_info=$(for branch in $(git branch -r | grep -v '\->'); do
  latest_commit=$(git log -1 --pretty=format:"%H" "$branch")
  commit_date=$(git show -s --format="%ct" "$latest_commit") # Unix timestamp
  echo "$commit_date $branch"
done)

# Step 2: Sort branches by creation date (descending) and take the last 100 created
latest_100=$(echo "$branch_info" | sort -nr | head -n 100 | awk '{print $2}')

info "🔍 Filtering for branches created by $TARGET_EMAIL..."

# Step 3: Loop through those 100 and filter by first commit author
while read -r remote_branch; do
  latest_commit=$(git log -1 --pretty=format:"%H" "$remote_branch")
  author_email=$(git show -s --format="%ae" "$latest_commit")

  if [[ "$author_email" == "$TARGET_EMAIL" ]]; then
    local_branch=${remote_branch#origin/}

    # log "✅ $remote_branch created by $author_email"

    if git show-ref --verify --quiet "refs/heads/$local_branch"; then
      info "⏭️ Local branch: '$local_branch' already exists. Skipping."
    else
      log "🆕 Checking out new branch: '$local_branch'"
      git checkout -b "$local_branch" --track "$remote_branch"
    fi
  fi
done <<< "$latest_100"