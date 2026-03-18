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

###################
# Video functions

# Helper: formats bytes to PB, TB, GB, MB, KB, or bytes with 2 decimal places
format_bytes() {
  local bytes=$1

  local KB=1024
  local MB=$((KB * 1024))
  local GB=$((MB * 1024))
  local TB=$((GB * 1024))
  local PB=$((TB * 1024))

  if [[ $bytes -ge $PB ]]; then
    local val
    val=$(echo "scale=2; $bytes / $PB" | bc)
    echo "${val} PB"
  elif [[ $bytes -ge $TB ]]; then
    local val
    val=$(echo "scale=2; $bytes / $TB" | bc)
    echo "${val} TB"
  elif [[ $bytes -ge $GB ]]; then
    local val
    val=$(echo "scale=2; $bytes / $GB" | bc)
    echo "${val} GB"
  elif [[ $bytes -ge $MB ]]; then
    local val
    val=$(echo "scale=2; $bytes / $MB" | bc)
    echo "${val} MB"
  elif [[ $bytes -ge $KB ]]; then
    local val
    val=$(echo "scale=2; $bytes / $KB" | bc)
    echo "${val} KB"
  else
    echo "${bytes} B"
  fi
}