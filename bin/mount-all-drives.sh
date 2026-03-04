#!/bin/bash

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
. "$SCRIPT_DIR/utils.sh" --source-only

# v2.0.4

# List of base drive names
# Each "object" is a string in format name|address
drives=(
  "smb://Meleys|smb://192.168.50.2"
  "smb://Vermithor|smb://192.168.50.3"
  "smb://Caraxes|smb://192.168.50.4"
  "smb://Syrax|smb://192.168.50.5"
  "smb://Vhagar|smb://192.168.50.6"
)

# Function to mount a network drive (you'll need to customize this)
mount_volume() {
  local name="$1"
  # Example mount command (modify according to your actual network setup)
  # Replace with actual SMB/AFP/NFS/URL paths
  log "Mounting ${name}"
  open "${name}"
}

# Example: Loop through and split into name and address
for entry in "${drives[@]}"; do
  IFS="|" read -r driveName address <<< "$entry"

  info ""
  info "Drive name: $driveName"
  info "Address: $address"

  # mount_volume "$address"
  mount_volume "$driveName"
done