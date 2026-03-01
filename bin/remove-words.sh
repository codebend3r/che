#!/bin/bash

. ~/bin/utils.sh --source-only

# DIR="."
DIR="/Volumes/Meraxes/Downloads"

# Words to remove (space-separated)
WORDS=("eporner" "spankbang" "porn", "watch")

# Check if the directory exists
if [ ! -d "$DIR" ]; then
  log "Error: Directory $DIR does not exist."
  exit 1
fi

string="Hello world, this is a test world."
word="world"

# Remove word (case-sensitive)
new_string=$(echo "$string" | sed "s/\b$word\b//g")

echo "$new_string"

# # Detect OS type (macOS or Linux)
# if [[ "$OSTYPE" == "darwin"* ]]; then
#   SED_CMD="sed -i ''"   # macOS (BSD sed)
# else
#   SED_CMD="sed -i"      # Linux (GNU sed)
# fi

# # Iterate over each file in the directory
# for file in "$DIR"/*; do
#   if [ -f "$file" ]; then
#     echo "Processing: $file"
    
#     for word in "${WORDS[@]}"; do
#       # Remove words (case-insensitive)
#       $SED_CMD "s/[[:<:]]$word[[:>:]]//Ig" "$file"
#     done
#   fi
# done

# Iterate over files in the directory
# for file in "$DIR"/*; do
#   if [ -f "$file" ]; then
#     log "Processing $file..."
#     for word in "${WORDS[@]}"; do
#       # newFileName=$file
#       newFileName=$(echo "$file" | sed "s/\b$word\b//Ig")

#       log "newFileName: $newFileName"

#       # sed -i "s/\b$word\b//Ig" "$file"
#       # sed -i '' "s/\b$word\b//Ig" "$file"
#     done
#   fi
# done

# log "Words removed successfully."
# log ""
# log ""
# log ""