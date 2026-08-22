# che 1.0.0 - generated file, do not edit.
#
# Generated from bin/commands.py by `che install`.
# To change a wrapper, edit that manifest and run `che install` again.
#
# Source this file (or let the `che install` block in your rc file do it):
#
#     . ~/Developer/git/che/shell/che.zsh
#
# Every wrapper is a shell function, so `type <name>` shows what it runs and
# `che doctor` can tell you when something it needs is missing.

# CHE_HOME is normally exported by the installed rc block. Fall back to this
# file's own location so a bare `source` of it also works.
if [ -z "${CHE_HOME:-}" ]; then
  CHE_HOME="${${(%):-%x}:A:h:h}"
fi

# Exported, not just set: every wrapper expands "$CHE_BIN", and a shell that
# replays the *functions* without re-reading this file - a `typeset -f` dump, an
# environment snapshot, any tool that rebuilds a shell from its exported
# environment - keeps the functions and drops a plain variable, leaving the
# wrappers to run "/che.py". CHE_HOME comes in exported by the rc block; this
# keeps everything derived from it exported too.
export CHE_BIN="${CHE_HOME}/bin"

# Any python3 on PATH by default. `che install` records the interpreter it
# verified (3.12+) in the rc block, which wins over this.
: "${CHE_PYTHON:=python3}"
export CHE_PYTHON

# Legacy name from the hand-maintained wrappers, kept so an older snippet in
# ~/.zshrc that still refers to it keeps resolving.
export SHELL_FUNCTIONS_BIN="${CHE_BIN}"

# Play the completion sound for a wrapper, then return the status it was given.
#
# playsound-N is defined outside this repo. Every wrapper used to call it
# unconditionally, which printed "command not found" on a machine that never
# had it; here a missing playsound is simply skipped. Set CHE_SOUNDS=0 to
# silence them all.
che_notify() {
  if [ "${CHE_SOUNDS:-1}" = "1" ] && command -v "playsound-$1" >/dev/null 2>&1; then
    "playsound-$1" >/dev/null 2>&1
  fi
  return "${2:-0}"
}

# The dispatcher. `che` with no arguments opens the interactive menu.
che() {
  if [ "$#" -eq 0 ]; then
    "$CHE_PYTHON" "$CHE_BIN/che.py"
  else
    "$CHE_PYTHON" "$CHE_BIN/che.py" "$@"
    che_notify 7 $?
  fi
}

# An alias sharing a name with a wrapper below is fatal, not cosmetic: zsh
# expands aliases while *parsing*, so `remove-metadata() {` becomes
# `find ./ -type f …() {` and the parse error aborts the rest of this file -
# taking every wrapper after it with it.
#
# So stash any colliding alias, define the functions, then put it back.
# Clearing it outright would silently replace a command the user aliased on
# purpose; restoring it keeps their alias winning at the prompt, exactly as it
# did before che was installed. `che doctor` reports the collision, and
# `\name` (backslash) reaches the wrapper without expanding the alias.
typeset -ga _che_stashed_aliases=()

_che_stash_aliases() {
  local name
  for name in "$@"; do
    if [[ -n ${aliases[$name]-} ]]; then
      _che_stashed_aliases+=("${name}=${aliases[$name]}")
      unalias -- "$name"
    fi
  done
}

_che_restore_aliases() {
  local entry
  for entry in "${_che_stashed_aliases[@]}"; do
    alias -- "$entry"
  done
  _che_stashed_aliases=()
}

_che_stash_aliases che all-actions all-actions-watch checkout-my-branches \
  clean-stale-branches clean-stale-branches-dr prune-worktrees \
  prune-worktrees-dr sync-all-branches sync-all-branches-dr \
  update-from-origin update-local-branches show-codecs fix-codecs \
  fix-codecs-dr find-video-mkv-issues validate-video-files \
  scan-videos-audio-language remove-metadata rename-video-file \
  delete-duplicate-videos delete-duplicate-videos-dr video-list \
  detect-green-magenta-videos find-movie-by-year largest-tv-shows \
  delete-by-ext delete-by-ext-dr delete-empty-folders \
  delete-empty-folders-dr delete-smb-files delete-smb-files-dr \
  files-under-size files-under-size-dr find-largest-files make-alpha-dir \
  compress-folders list-permission mount-all-drives eject-all-drives \
  eject-all-drives-dr ping-nas update-brew update-brew-dr btop

# --------------------------------------------------------------------------
# Git - Branch hygiene, worktrees and GitHub Actions
# --------------------------------------------------------------------------

# GitHub Actions status for every open PR you authored
all-actions() {
  "$CHE_PYTHON" "$CHE_BIN/git/all-actions.py" "$@"
}

# Same as all-actions, refreshed on an interval
all-actions-watch() {
  "$CHE_PYTHON" "$CHE_BIN/git/all-actions.py" --watch "$@"
}

# Check out recent remote branches you authored that aren't local yet
checkout-my-branches() {
  "$CHE_PYTHON" "$CHE_BIN/git/checkout-my-branches.py" "$@"
  che_notify 7 $?
}

# Delete local branches whose upstream is gone
clean-stale-branches() {
  DRY_RUN=false "$CHE_PYTHON" "$CHE_BIN/git/clean-stale-branches.py" "$@"
  che_notify 4 $?
}

# Delete local branches whose upstream is gone (preview only)
clean-stale-branches-dr() {
  DRY_RUN=true "$CHE_PYTHON" "$CHE_BIN/git/clean-stale-branches.py" "$@"
  che_notify 7 $?
}

# Remove every linked worktree, then prune stale admin records
prune-worktrees() {
  DRY_RUN=false "$CHE_PYTHON" "$CHE_BIN/git/prune-worktrees.py" "$@"
  che_notify 4 $?
}

# Remove every linked worktree, then prune stale admin records (preview only)
prune-worktrees-dr() {
  DRY_RUN=true "$CHE_PYTHON" "$CHE_BIN/git/prune-worktrees.py" "$@"
  che_notify 7 $?
}

# Push every worktree, collapse the pushed ones, then tidy branches
sync-all-branches() {
  DRY_RUN=false "$CHE_PYTHON" "$CHE_BIN/git/sync-all-branches.py" "$@"
  che_notify 7 $?
}

# Push every worktree, collapse the pushed ones, then tidy branches (preview only)
sync-all-branches-dr() {
  DRY_RUN=true "$CHE_PYTHON" "$CHE_BIN/git/sync-all-branches.py" "$@"
  che_notify 7 $?
}

# Same as sync-all-branches but never pushes: fetch, collapse, rebase
update-from-origin() {
  DRY_RUN=false "$CHE_PYTHON" "$CHE_BIN/git/sync-all-branches.py" --no-push "$@"
  che_notify 7 $?
}

# Rebase every local branch that has an upstream onto origin
update-local-branches() {
  "$CHE_PYTHON" "$CHE_BIN/git/update-local-branches.py" "$@"
  che_notify 5 $?
}

# --------------------------------------------------------------------------
# Video - Codecs, renaming, dedupe and metadata
# --------------------------------------------------------------------------

# Report media files outside the Direct Play codec/container set
show-codecs() {
  "$CHE_PYTHON" "$CHE_BIN/video/show-codecs.py" "$@"
  che_notify 6 $?
}

# Re-encode media to h265/aac mp4 so it Direct Plays
fix-codecs() {
  DRY_RUN=false "$CHE_PYTHON" "$CHE_BIN/video/fix-codecs.py" "$@"
  che_notify 7 $?
}

# Re-encode media to h265/aac mp4 so it Direct Plays (preview only)
fix-codecs-dr() {
  DRY_RUN=true "$CHE_PYTHON" "$CHE_BIN/video/fix-codecs.py" "$@"
  che_notify 7 $?
}

# Scan MKV files and estimate Plex direct-play compatibility
find-video-mkv-issues() {
  "$CHE_PYTHON" "$CHE_BIN/video/find-video-mkv-issues.py" "$@"
  che_notify 4 $?
}

# Check .mp4/.mkv files decode by playing one frame with mpv
validate-video-files() {
  "$CHE_PYTHON" "$CHE_BIN/video/validate-video-files.py" "$@"
  che_notify 2 $?
}

# Print the audio language tags of every video under a path
scan-videos-audio-language() {
  "$CHE_PYTHON" "$CHE_BIN/video/scan-videos-audio-language.py" "$@"
  che_notify 3 $?
}

# Strip all metadata from video files recursively
remove-metadata() {
  "$CHE_PYTHON" "$CHE_BIN/video/remove-metadata.py" "$@"
  che_notify 4 $?
}

# Title-case video filenames (and optionally their folders)
rename-video-file() {
  "$CHE_PYTHON" "$CHE_BIN/video/rename-video-file.py" "$@"
  che_notify 5 $?
}

# Delete duplicate MKV/MP4 files under a root directory
delete-duplicate-videos() {
  DRY_RUN=false "$CHE_PYTHON" "$CHE_BIN/video/delete-duplicate-videos.py" "$@"
  che_notify 6 $?
}

# Delete duplicate MKV/MP4 files under a root directory (preview only)
delete-duplicate-videos-dr() {
  DRY_RUN=true "$CHE_PYTHON" "$CHE_BIN/video/delete-duplicate-videos.py" "$@"
  che_notify 6 $?
}

# List .mp4/.mkv files under a path with human-readable sizes
video-list() {
  "$CHE_PYTHON" "$CHE_BIN/video/video-list.py" "$@"
  che_notify 5 $?
}

# Detect videos with the green/magenta chroma artifact
detect-green-magenta-videos() {
  "$CHE_PYTHON" "$CHE_BIN/video/detect-green-magenta-videos.py" "$@"
  che_notify 3 $?
}

# Find movie folders whose name ends with "(YYYY)"
find-movie-by-year() {
  "$CHE_PYTHON" "$CHE_BIN/video/find-movie-by-year.py" "$@"
  che_notify 2 $?
}

# Rank TV show folders in a library by total size on disk
largest-tv-shows() {
  "$CHE_PYTHON" "$CHE_BIN/video/largest-tv-shows.py" "$@"
  che_notify 2 $?
}

# --------------------------------------------------------------------------
# Files - Delete, compress and inspect by size or extension
# --------------------------------------------------------------------------

# Delete files under a path matching a set of extensions
delete-by-ext() {
  DRY_RUN=false "$CHE_PYTHON" "$CHE_BIN/files/delete-by-ext.py" "$@"
  che_notify 6 $?
}

# Delete files under a path matching a set of extensions (preview only)
delete-by-ext-dr() {
  DRY_RUN=true "$CHE_PYTHON" "$CHE_BIN/files/delete-by-ext.py" "$@"
  che_notify 7 $?
}

# Delete truly-empty directories under a path, cascading upwards
delete-empty-folders() {
  DRY_RUN=false "$CHE_PYTHON" "$CHE_BIN/files/delete-empty-folders.py" "$@"
  che_notify 6 $?
}

# Delete truly-empty directories under a path, cascading upwards (preview only)
delete-empty-folders-dr() {
  DRY_RUN=true "$CHE_PYTHON" "$CHE_BIN/files/delete-empty-folders.py" "$@"
  che_notify 7 $?
}

# Delete .smbdelete* files left behind by an SMB share
delete-smb-files() {
  DRY_RUN=false "$CHE_PYTHON" "$CHE_BIN/files/delete-smb-files.py" "$@"
  che_notify 6 $?
}

# Delete .smbdelete* files left behind by an SMB share (preview only)
delete-smb-files-dr() {
  DRY_RUN=true "$CHE_PYTHON" "$CHE_BIN/files/delete-smb-files.py" "$@"
  che_notify 7 $?
}

# Find video files at or under a size threshold
files-under-size() {
  DRY_RUN=false "$CHE_PYTHON" "$CHE_BIN/files/files-under-size.py" "$@"
  che_notify 4 $?
}

# Find video files at or under a size threshold (preview only)
files-under-size-dr() {
  DRY_RUN=true "$CHE_PYTHON" "$CHE_BIN/files/files-under-size.py" "$@"
  che_notify 7 $?
}

# List the largest files under a path, biggest first
find-largest-files() {
  "$CHE_PYTHON" "$CHE_BIN/files/find-largest-files.py" "$@"
  che_notify 2 $?
}

# Create '#' and A-Z bucket folders under a parent directory
make-alpha-dir() {
  "$CHE_PYTHON" "$CHE_BIN/files/make-alpha-dir.py" "$@"
  che_notify 4 $?
}

# Zip every immediate subfolder of a path at max compression
compress-folders() {
  "$CHE_PYTHON" "$CHE_BIN/files/compress-folders.py" "$@"
  che_notify 7 $?
}

# Show ownership and mode of a volume under /Volumes
list-permission() {
  command ls -ld "/Volumes/$1"
  che_notify 7 $?
}

# --------------------------------------------------------------------------
# Drives - Mount, eject and keep-alive for the NAS volumes
# --------------------------------------------------------------------------

# Mount all NAS drives over SMB via AppleScript
mount-all-drives() {
  "$CHE_PYTHON" "$CHE_BIN/drives/mount-all-drives.py" "$@"
  che_notify 7 $?
}

# Eject all NAS volumes from /Volumes
eject-all-drives() {
  "$CHE_PYTHON" "$CHE_BIN/drives/eject-all-drives.py" "$@"
  che_notify 7 $?
}

# Eject all NAS volumes from /Volumes (preview only)
eject-all-drives-dr() {
  "$CHE_PYTHON" "$CHE_BIN/drives/eject-all-drives.py" --dry-run "$@"
  che_notify 7 $?
}

# Keep-alive pinger that remounts a NAS drive that dropped off
ping-nas() {
  "$CHE_PYTHON" "$CHE_BIN/drives/ping-nas.py" "$@"
}

# --------------------------------------------------------------------------
# System - Homebrew, monitoring and the machine itself
# --------------------------------------------------------------------------

# Update Homebrew, upgrade formulae and casks, then clean up
update-brew() {
  "$CHE_PYTHON" "$CHE_BIN/system/update-brew.py" "$@"
  che_notify 7 $?
}

# Update Homebrew, upgrade formulae and casks, then clean up (preview only)
update-brew-dr() {
  "$CHE_PYTHON" "$CHE_BIN/system/update-brew.py" --dry-run "$@"
  che_notify 7 $?
}

# Launch btop with a gruvbox theme matching the macOS appearance
btop() {
  "$CHE_PYTHON" "$CHE_BIN/system/btop-launch.py" "$@"
}

_che_restore_aliases

# Completions. compdef only exists once compinit has run; when it has not,
# skip quietly rather than erroring at shell start.
if whence -w compdef >/dev/null 2>&1 && [ -r "${CHE_HOME}/shell/completions/_che" ]; then
  . "${CHE_HOME}/shell/completions/_che"
fi
