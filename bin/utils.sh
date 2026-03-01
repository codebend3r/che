#!/usr/bin/env bash

# Color definitions
NC='\033[0m'       # No Color
RED='\033[1;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[1;34m'
CYAN='\033[1;36m'
MAGENTA='\033[1;35m'

# Generic color logger
# log_color() {
#   local COLOR=$1
#   local MESSAGE=$2
#   printf '%b %s %b\n' "$COLOR" "$MESSAGE" "$NC"
# }

log_color() {
  local COLOR=$1
  local MESSAGE=$2
  printf '%b%b%b\n' "$COLOR" "$MESSAGE" "$NC"
}

# Specific log functions
log() {
  log_color "$GREEN" "$1"
}

warning() {
  log_color "$RED" "$1"
}

info() {
  log_color "$CYAN" "$1"
}

note() {
  log_color "$YELLOW" "$1"
}

success() {
  log_color "$MAGENTA" "$1"
}

human_size() {
  local bytes=$1

  if (( bytes >= 1073741824 )); then
    awk -v b="$bytes" 'BEGIN { printf "%.2f GB", b / 1073741824 }'
  elif (( bytes >= 1048576 )); then
    awk -v b="$bytes" 'BEGIN { printf "%.2f MB", b / 1048576 }'
  elif (( bytes >= 1024 )); then
    awk -v b="$bytes" 'BEGIN { printf "%.2f KB", b / 1024 }'
  else
    printf "%d B" "$bytes"
  fi
}

###################
# Video functions

# Helper: formats bytes to GB, MB, KB, or bytes with 2 decimal places
format_bytes() {
  local bytes=$1
  if [[ $bytes -ge 1073741824 ]]; then
    local gb=$(echo "scale=2; $bytes / (1024 * 1024 * 1024)" | bc)
    echo "${gb} GB"
  elif [[ $bytes -ge 1048576 ]]; then
    local mb=$(echo "scale=2; $bytes / (1024 * 1024)" | bc)
    echo "${mb} MB"
  elif [[ $bytes -ge 1024 ]]; then
    local kb=$(echo "scale=2; $bytes / 1024" | bc)
    echo "${kb} KB"
  else
    echo "${bytes} B"
  fi
}