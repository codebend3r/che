#!/bin/bash

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
. "$SCRIPT_DIR/utils.sh" --source-only

# v2.0.4

info "Running command in $(pwd)"

# Each "object" is a string in format driveName|address|ip
drives=(
  "Meleys|smb://Meleys|192.168.50.2"
  "Caraxes|smb://Caraxes|192.168.50.4"
  "Syrax|smb://Syrax|192.168.50.5"
  "Vermithor|smb://Vermithor|192.168.50.3"
  "Vhagar|smb://Vhagar|192.168.50.6"
)

# 192.168.50.2
# 192.168.50.3
# 192.168.50.4
# 192.168.50.5
# 192.168.50.6

# Function to eject a volume if mounted
eject_volume() {
  local name="$1"
  diskutil unmount force /Volumes/${name}
  # osascript -e 'tell application "Finder" to eject "${name}"'
  sudo rmdir /Volumes/${name}
  log "Ejected /Volumes/${name}"
}

# Example: Loop through and split into name, address, ip
for entry in "${drives[@]}"; do
  IFS="|" read -r driveName address ip <<< "$entry"

  info "Drive name: $driveName"
  info "Address: $address"
  info "IP: $ip"

  eject_volume "$driveName"
  eject_volume "${driveName}-1"
  eject_volume "$ip"
done