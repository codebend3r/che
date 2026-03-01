#!/bin/bash

. ~/bin/utils.sh --source-only

# List of base drive names
# Each "object" is a string in format name|address
drives=(
  "Meleys|smb://192.168.50.2"
  "Vermithor|smb://192.168.50.3"
  "Caraxes|smb://192.168.50.4"
  "Syrax|smb://192.168.50.5"
  "Vhagar|smb://192.168.50.6"
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

  mount_volume "$address"
done