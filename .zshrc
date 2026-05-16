. ~/Developer/git/shell-functions/bin/utils.sh --source-only

# -----------------------------------------------------------------------------
# Shell functions (single source of truth)
# Prefer ~/Developer/git/shell-functions/bin/
# -----------------------------------------------------------------------------

SHELL_FUNCTIONS_BIN="${HOME}/Developer/git/shell-functions/bin"

# -----------------------------------------------------------------------------
# Git helpers
# -----------------------------------------------------------------------------

clean-stale-branches() {
  DRY_RUN=false bash "${SHELL_FUNCTIONS_BIN}/git/clean-stale-branches.sh"
  playsound-4
}

clean-stale-branches-dr() {
  DRY_RUN=true bash "${SHELL_FUNCTIONS_BIN}/git/clean-stale-branches.sh"
  playsound-7
}

update-local-branches() {
  bash "${SHELL_FUNCTIONS_BIN}/git/update-local-branches.sh" "$@"
  playsound-5
}

checkout-my-branches() {
  bash "${SHELL_FUNCTIONS_BIN}/git/checkout-my-branches.sh" "$@"
  playsound-7
}

prune-worktrees() {
  DRY_RUN=false bash "${SHELL_FUNCTIONS_BIN}/git/prune-worktrees.sh" "$@"
  playsound-4
}

prune-worktrees-dr() {
  DRY_RUN=true bash "${SHELL_FUNCTIONS_BIN}/git/prune-worktrees.sh" "$@"
  playsound-7
}

# One-shot: pull every kind of "latest" from origin into the local repo.
# Read-only against origin — fetches/prunes, never pushes.
update-from-origin() {
  DRY_RUN=false bash "${SHELL_FUNCTIONS_BIN}/git/prune-worktrees.sh"
  DRY_RUN=false bash "${SHELL_FUNCTIONS_BIN}/git/clean-stale-branches.sh"
  bash "${SHELL_FUNCTIONS_BIN}/git/update-local-branches.sh"
  bash "${SHELL_FUNCTIONS_BIN}/git/checkout-my-branches.sh"
  playsound-7
}

# -----------------------------------------------------------------------------
# Video / media helpers
# -----------------------------------------------------------------------------

rename-video-file() {
  bash "${SHELL_FUNCTIONS_BIN}/video/rename-video-file.sh" "$@"
  playsound-5
}

show-codecs() {
  bash "${SHELL_FUNCTIONS_BIN}/video/show-codecs.sh" "$@"
  playsound-6
}

fix-codecs() {
  bash "${SHELL_FUNCTIONS_BIN}/video/fix-codecs.sh" "$@"
  playsound-7
}

find-video-mkv-issues() {
  bash "${SHELL_FUNCTIONS_BIN}/video/find-video-mkv-issues.sh" "$@"
  playsound-4
}

validate-video-files() {
  bash "${SHELL_FUNCTIONS_BIN}/video/validate-video-files.sh" "$@"
  playsound-2
}

scan-videos-audio-language() {
  bash "${SHELL_FUNCTIONS_BIN}/video/scan-videos-audio-language.sh" "$@"
  playsound-3
}

remove-metadata() {
  bash "${SHELL_FUNCTIONS_BIN}/video/remove-metadata.sh" "$@"
  playsound-4
}

delete-duplicate-videos() {
  bash "${SHELL_FUNCTIONS_BIN}/video/delete-duplicate-videos.sh" "$@"
  playsound-6
}

video-list() {
  bash "${SHELL_FUNCTIONS_BIN}/video/video-list.sh" "$@"
  playsound-5
}

# -----------------------------------------------------------------------------
# Filesystem cleanup / utilities
# -----------------------------------------------------------------------------

delete-empty-folders() {
  bash "${SHELL_FUNCTIONS_BIN}/files/delete-empty-folders.sh" "$@"
  playsound-6
}

delete-smb-files() {
  bash "${SHELL_FUNCTIONS_BIN}/files/delete-smb-files.sh" "$@"
  playsound-6
}

delete-by-ext() {
  bash "${SHELL_FUNCTIONS_BIN}/files/delete-by-ext.sh" "$@"
  playsound-6
}

files-under-size() {
  bash "${SHELL_FUNCTIONS_BIN}/files/files-under-size.sh" "$@"
  playsound-4
}

find-largest-files() {
  bash "${SHELL_FUNCTIONS_BIN}/files/find-largest-files.sh" "$@"
  playsound-2
}

make-alpha-dir() {
  bash "${SHELL_FUNCTIONS_BIN}/files/make-alpha-dir.sh" "$@"
  playsound-4
}

compress-folders() {
  bash "${SHELL_FUNCTIONS_BIN}/files/compress-folders.sh" "$@"
  playsound-7
}

list-permission() {
  ls -ld "/Volumes/$1"
  playsound-7
}

# -----------------------------------------------------------------------------
# Movies
# -----------------------------------------------------------------------------

find-movie-by-year() {
  bash "${SHELL_FUNCTIONS_BIN}/video/find-movie-by-year.sh" "$@"
  playsound-2
}

largest-tv-shows() {
  bash "${SHELL_FUNCTIONS_BIN}/video/largest-tv-shows.sh" "$@"
  playsound-2
}

# -----------------------------------------------------------------------------
# NAS / drives
# -----------------------------------------------------------------------------

mount-all-drives() {
  bash "${SHELL_FUNCTIONS_BIN}/drives/mount-all-drives.sh" "$@"
  playsound-7
}

eject-all-drives() {
  bash "${SHELL_FUNCTIONS_BIN}/drives/eject-all-drives.sh" "$@"
  playsound-7
}

eject-all-drives-dr() {
  bash "${SHELL_FUNCTIONS_BIN}/drives/eject-all-drives.sh" --dry-run "$@"
  playsound-7
}

ping-nas() {
  bash "${SHELL_FUNCTIONS_BIN}/drives/ping-nas.sh" "$@"
}

# -----------------------------------------------------------------------------
# System / packages
# -----------------------------------------------------------------------------

update-brew() {
  bash "${SHELL_FUNCTIONS_BIN}/system/update-brew.sh" "$@"
  playsound-7
}

update-brew-dr() {
  bash "${SHELL_FUNCTIONS_BIN}/system/update-brew.sh" --dry-run "$@"
  playsound-7
}