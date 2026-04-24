#!/bin/bash

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
. "$SCRIPT_DIR/utils.sh" --source-only

# Usage:
#   rename-video-file [--path=/path/to/dir] [--recursive] [--capitalize-preps=true|false] [--dry-run=true|false] [--ignore-words=WORD1,WORD2]

ROOT_DIR=""
CAPITALIZE_PREPS="false"
RECURSIVE="false"
DRY_RUN="true"
IGNORE_WORDS=""

# Parse arguments
while [[ $# -gt 0 ]]; do
  case "$1" in
    --path=*)
      ROOT_DIR="${1#*=}";
      shift
      ;;
    --recursive=*)
      RECURSIVE="${1#*=}";
      shift
      ;;
    --recursive)
      RECURSIVE="true";
      shift
      ;;
    --dry-run=*)
      DRY_RUN="${1#*=}";
      shift
      ;;
    --dry-run)
      DRY_RUN="true";
      shift
      ;;
    --ignore-words=*)
      IGNORE_WORDS="${1#*=}";
      shift
      ;;
    --capitalize-preps=*)
      CAPITALIZE_PREPS="${1#*=}";
      shift
      ;;
    --capitalize-preps)
      CAPITALIZE_PREPS="true";
      shift
      ;;
    -h|--help)
      warning "Usage: $0 --path=/path/to/media [--recursive] [--capitalize-preps=true|false] [--dry-run=true|false] [--ignore-words=WORD1,WORD2]"
      exit 0
      ;;
    *)
      warning "Unknown argument: $1"
      warning "Usage: $0 --path=/path/to/media [--recursive] [--capitalize-preps=true|false] [--dry-run=true|false] [--ignore-words=WORD1,WORD2]"
      exit 1
      ;;
  esac
done

note "Scanning: $ROOT_DIR"
note "Recursive: $RECURSIVE"
note "Capitalize Prepositions: $CAPITALIZE_PREPS"
note "Dry Run: $DRY_RUN"
if [[ -n "$IGNORE_WORDS" ]]; then
  note "Ignore Words: $IGNORE_WORDS"
fi
note "----------------------------------------------------"

FIND_OPTS=()
if [[ "$RECURSIVE" == "false" ]]; then
  FIND_OPTS+=("-maxdepth" "1")
fi

# Loop through all .mp4 files in the specified path
find "$ROOT_DIR" "${FIND_OPTS[@]}" -type f -name "*.mp4" -print0 | while IFS= read -r -d '' file; do
  [[ -f "$file" ]] || continue
  
  # info "Checking file: $(basename "$file")"
  
  filename=$(basename "$file")
  dir=$(dirname "$file")

  # Normalize all forms of single quotes/apostrophes/backticks to a standard straight apostrophe
  filename=$(echo "$filename" | sed -e "s/’/'/g" -e "s/‘/'/g" -e "s/´/'/g" -e 's/`/'\''/g')

  # Add spaces around all dashes, except between all-caps words and numbers (e.g. CON-323 stays CON-323)
  filename=$(echo "$filename" | perl -pe 's/\s*-\s*/ - /g; s/\b([A-Z]+)\s*-\s*([0-9]+)/$1-$2/g')
  
  if [[ $filename =~ (.*-\ )([^.]+)(\..*) ]]; then
    # Has a dash format
    prefix="${BASH_REMATCH[1]}"
    title="${BASH_REMATCH[2]}"
    ext="${BASH_REMATCH[3]}"
  elif [[ $filename =~ ([^.]+)(\..*) ]]; then
    # No dash format
    prefix=""
    title="${BASH_REMATCH[1]}"
    ext="${BASH_REMATCH[2]}"
  else
    warning "Could not parse filename: $filename"
    continue
  fi
  
  # Title case both the prefix and title portions (works on macOS using perl).
  # This capitalizes the first letter of every regular word and lowercases the rest,
  # while keeping/making video codes entirely uppercase.
  if [[ -n "$IGNORE_WORDS" ]]; then
    ignore_pattern="|\b(${IGNORE_WORDS//,/|})\b"
    prefix_cased=$(echo "$prefix" | perl -pe "s/\b([a-zA-Z]{3,5}-[0-9]{3,5})\b${ignore_pattern}|\b(\w)(\w*)/\$1 ? uc(\$1) : \$2 ? \$2 : \"\U\$3\L\$4\"/ge")
    title_cased=$(echo "$title" | perl -pe "s/\b([a-zA-Z]{3,5}-[0-9]{3,5})\b${ignore_pattern}|\b(\w)(\w*)/\$1 ? uc(\$1) : \$2 ? \$2 : \"\U\$3\L\$4\"/ge")
  else
    prefix_cased=$(echo "$prefix" | perl -pe 's/\b([a-zA-Z]{3,5}-[0-9]{3,5})\b|\b(\w)(\w*)/$1 ? uc($1) : "\U$2\L$3"/ge')
    title_cased=$(echo "$title" | perl -pe 's/\b([a-zA-Z]{3,5}-[0-9]{3,5})\b|\b(\w)(\w*)/$1 ? uc($1) : "\U$2\L$3"/ge')
  fi
  
  if [[ "$CAPITALIZE_PREPS" == "false" ]]; then
    # Lowercase articles, prepositions, and conjunctions when flag is false
    prefix_cased=$(echo "$prefix_cased" | perl -pe 's/\b(And|The|A|An|By|For|In|Of|On|To|With|At|But|Or|Nor|So|Yet|As)\b/\L$1/gi')
    title_cased=$(echo "$title_cased" | perl -pe 's/\b(And|The|A|An|By|For|In|Of|On|To|With|At|But|Or|Nor|So|Yet|As)\b/\L$1/gi')
    
    # Always ensure the very first word of the title is capitalized, even if it's a preposition or has leading punctuation 
    title_cased=$(echo "$title_cased" | perl -pe 's/^([^A-Za-z]*)([A-Za-z])/$1\U$2/')
    prefix_cased=$(echo "$prefix_cased" | perl -pe 's/^([^A-Za-z]*)([A-Za-z])/$1\U$2/')
    
    # If the title happens to have a dash in it (like "Show-the movie"), ensure the word immediately after the dash is capitalized
    title_cased=$(echo "$title_cased" | perl -pe 's/(-\s*)([^A-Za-z]*)([A-Za-z])/$1$2\U$3/g')
    prefix_cased=$(echo "$prefix_cased" | perl -pe 's/(-\s*)([^A-Za-z]*)([A-Za-z])/$1$2\U$3/g')
  fi

  new_filename="${prefix_cased}${title_cased}${ext}"
  
  # Ensure any 1-2 letters after an apostrophe are lowercase across the entire filename (e.g. I'm, You've, Friend's)
  new_filename=$(echo "$new_filename" | perl -pe "s/'([A-Za-z]{1,2})\b/'\L\$1/g")
  
  new="${dir}/${new_filename}"
  
  if [[ "$file" != "$new" ]]; then
    if [[ "$DRY_RUN" == "true" ]]; then
      log "[DRY RUN] Would rename: $(basename "$file") -> $(basename "$new")"
    else
      log "Renaming: $(basename "$file") -> $(basename "$new")"
      mv -v "$file" "$new"
    fi
  else
    warning "Skipping (already correct format): $(basename "$file")"
  fi
done
