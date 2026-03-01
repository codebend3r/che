#!/bin/bash

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
. "$SCRIPT_DIR/utils.sh" --source-only

set -euo pipefail

# v2.0.3

info "Running command in $(pwd)"

# Loop through each item in the current directory
for dir in */; do
  # Remove trailing slash to get the folder name
  folder_name="${dir%/}"

  # Skip if it's not a directory
  [ -d "$folder_name" ] || continue

  info "Compressing '$folder_name'..."

  # Create a zip file with the same name as the folder using max compression (-9)
  zip -r -9 "${folder_name}.zip" "$folder_name"

  info "Finished compressing '$folder_name'"
  # tar -cJf "${folder_name}.tar.xz" "$folder_name"
done

info "Compression complete."
