# -----------------------------------------------------------------------------
# Shell functions (single source of truth)
# Prefer ~/Developer/git/shell-functions/bin/
# -----------------------------------------------------------------------------

SHELL_FUNCTIONS_BIN="${HOME}/Developer/git/shell-functions/bin"

# -----------------------------------------------------------------------------
# Git helpers
# -----------------------------------------------------------------------------

clean-stale-branches() {
  DRY_RUN=false python3 "${SHELL_FUNCTIONS_BIN}/git/clean-stale-branches.py"
  playsound-4
}

clean-stale-branches-dr() {
  DRY_RUN=true python3 "${SHELL_FUNCTIONS_BIN}/git/clean-stale-branches.py"
  playsound-7
}

update-local-branches() {
  python3 "${SHELL_FUNCTIONS_BIN}/git/update-local-branches.py" "$@"
  playsound-5
}

checkout-my-branches() {
  python3 "${SHELL_FUNCTIONS_BIN}/git/checkout-my-branches.py" "$@"
  playsound-7
}

all-actions() {
  python3 "${SHELL_FUNCTIONS_BIN}/git/all-actions.py" "$@"
}

all-actions-watch() {
  python3 "${SHELL_FUNCTIONS_BIN}/git/all-actions.py" --watch "$@"
}

prune-worktrees() {
  DRY_RUN=false python3 "${SHELL_FUNCTIONS_BIN}/git/prune-worktrees.py" "$@"
  playsound-4
}

prune-worktrees-dr() {
  DRY_RUN=true python3 "${SHELL_FUNCTIONS_BIN}/git/prune-worktrees.py" "$@"
  playsound-7
}

# One-shot: push every worktree to origin, collapse the pushed ones back into
# plain local branches, then run the usual branch hygiene. This DOES push.
sync-all-branches() {
  DRY_RUN=false python3 "${SHELL_FUNCTIONS_BIN}/git/sync-all-branches.py" "$@"
  playsound-7
}

sync-all-branches-dr() {
  DRY_RUN=true python3 "${SHELL_FUNCTIONS_BIN}/git/sync-all-branches.py" "$@"
  playsound-7
}

# One-shot: pull every kind of "latest" from origin into the local repo.
# Read-only against origin — fetches/prunes, never pushes. Worktrees that are
# already fully pushed are still collapsed; unpushed ones are left alone.
update-from-origin() {
  DRY_RUN=false python3 "${SHELL_FUNCTIONS_BIN}/git/sync-all-branches.py" --no-push "$@"
  playsound-7
}

# -----------------------------------------------------------------------------
# Video / media helpers
# -----------------------------------------------------------------------------

rename-video-file() {
  python3 "${SHELL_FUNCTIONS_BIN}/video/rename-video-file.py" "$@"
  playsound-5
}

show-codecs() {
  python3 "${SHELL_FUNCTIONS_BIN}/video/show-codecs.py" "$@"
  playsound-6
}

fix-codecs() {
  DRY_RUN=false python3 "${SHELL_FUNCTIONS_BIN}/video/fix-codecs.py" "$@"
  playsound-7
}

fix-codecs-dr() {
  DRY_RUN=true python3 "${SHELL_FUNCTIONS_BIN}/video/fix-codecs.py" "$@"
  playsound-7
}

find-video-mkv-issues() {
  python3 "${SHELL_FUNCTIONS_BIN}/video/find-video-mkv-issues.py" "$@"
  playsound-4
}

validate-video-files() {
  python3 "${SHELL_FUNCTIONS_BIN}/video/validate-video-files.py" "$@"
  playsound-2
}

scan-videos-audio-language() {
  python3 "${SHELL_FUNCTIONS_BIN}/video/scan-videos-audio-language.py" "$@"
  playsound-3
}

remove-metadata() {
  python3 "${SHELL_FUNCTIONS_BIN}/video/remove-metadata.py" "$@"
  playsound-4
}

delete-duplicate-videos() {
  DRY_RUN=false python3 "${SHELL_FUNCTIONS_BIN}/video/delete-duplicate-videos.py" "$@"
  playsound-6
}

delete-duplicate-videos-dr() {
  DRY_RUN=true python3 "${SHELL_FUNCTIONS_BIN}/video/delete-duplicate-videos.py" "$@"
  playsound-6
}

video-list() {
  python3 "${SHELL_FUNCTIONS_BIN}/video/video-list.py" "$@"
  playsound-5
}

detect-green-magenta-videos() {
  python3 "${SHELL_FUNCTIONS_BIN}/video/detect-green-magenta-videos.py" "$@"
  playsound-3
}

# -----------------------------------------------------------------------------
# Filesystem cleanup / utilities
# -----------------------------------------------------------------------------

delete-empty-folders() {
  DRY_RUN=false python3 "${SHELL_FUNCTIONS_BIN}/files/delete-empty-folders.py" "$@"
  playsound-6
}

delete-empty-folders-dr() {
  DRY_RUN=true python3 "${SHELL_FUNCTIONS_BIN}/files/delete-empty-folders.py" "$@"
  playsound-7
}

delete-smb-files() {
  DRY_RUN=false python3 "${SHELL_FUNCTIONS_BIN}/files/delete-smb-files.py" "$@"
  playsound-6
}

delete-smb-files-dr() {
  DRY_RUN=true python3 "${SHELL_FUNCTIONS_BIN}/files/delete-smb-files.py" "$@"
  playsound-7
}

delete-by-ext() {
  DRY_RUN=false python3 "${SHELL_FUNCTIONS_BIN}/files/delete-by-ext.py" "$@"
  playsound-6
}

delete-by-ext-dr() {
  DRY_RUN=true python3 "${SHELL_FUNCTIONS_BIN}/files/delete-by-ext.py" "$@"
  playsound-7
}

files-under-size() {
  DRY_RUN=false python3 "${SHELL_FUNCTIONS_BIN}/files/files-under-size.py" "$@"
  playsound-4
}

files-under-size-dr() {
  DRY_RUN=true python3 "${SHELL_FUNCTIONS_BIN}/files/files-under-size.py" "$@"
  playsound-7
}

find-largest-files() {
  python3 "${SHELL_FUNCTIONS_BIN}/files/find-largest-files.py" "$@"
  playsound-2
}

make-alpha-dir() {
  python3 "${SHELL_FUNCTIONS_BIN}/files/make-alpha-dir.py" "$@"
  playsound-4
}

compress-folders() {
  python3 "${SHELL_FUNCTIONS_BIN}/files/compress-folders.py" "$@"
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
  python3 "${SHELL_FUNCTIONS_BIN}/video/find-movie-by-year.py" "$@"
  playsound-2
}

largest-tv-shows() {
  python3 "${SHELL_FUNCTIONS_BIN}/video/largest-tv-shows.py" "$@"
  playsound-2
}

# -----------------------------------------------------------------------------
# NAS / drives
# -----------------------------------------------------------------------------

mount-all-drives() {
  python3 "${SHELL_FUNCTIONS_BIN}/drives/mount-all-drives.py" "$@"
  playsound-7
}

eject-all-drives() {
  python3 "${SHELL_FUNCTIONS_BIN}/drives/eject-all-drives.py" "$@"
  playsound-7
}

eject-all-drives-dr() {
  python3 "${SHELL_FUNCTIONS_BIN}/drives/eject-all-drives.py" --dry-run "$@"
  playsound-7
}

ping-nas() {
  python3 "${SHELL_FUNCTIONS_BIN}/drives/ping-nas.py" "$@"
}

# -----------------------------------------------------------------------------
# System / packages
# -----------------------------------------------------------------------------

update-brew() {
  python3 "${SHELL_FUNCTIONS_BIN}/system/update-brew.py" "$@"
  playsound-7
}

update-brew-dr() {
  python3 "${SHELL_FUNCTIONS_BIN}/system/update-brew.py" --dry-run "$@"
  playsound-7
}

# Launch btop with a gruvbox theme matching the macOS appearance.
btop() {
  python3 "${SHELL_FUNCTIONS_BIN}/system/btop-launch.py" "$@"
}