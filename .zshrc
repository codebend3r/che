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
  DRY_RUN=false bash "${SHELL_FUNCTIONS_BIN}/clean-stale-branches.sh"
  playsound-4
}

clean-stale-branches-dr() {
  DRY_RUN=true bash "${SHELL_FUNCTIONS_BIN}/clean-stale-branches.sh"
  playsound-7
}

update-local-branches() {
  bash "${SHELL_FUNCTIONS_BIN}/update-local-branches.sh" "$@"
  playsound-5
}

checkout-my-branches() {
  bash "${SHELL_FUNCTIONS_BIN}/checkout-my-branches.sh" "$@"
  playsound-7
}

rebase-all-branches() {
  bash "${SHELL_FUNCTIONS_BIN}/rebase-all-branches.sh" "$@"
  playsound-3
}

# -----------------------------------------------------------------------------
# Video / media helpers
# -----------------------------------------------------------------------------

show-codecs() {
  bash "${SHELL_FUNCTIONS_BIN}/show-codecs.sh" "$@"
  playsound-6
}

fix-codecs() {
  bash "${SHELL_FUNCTIONS_BIN}/fix-codecs.sh" "$@"
  playsound-7
}

find-video-mkv-issues() {
  bash "${SHELL_FUNCTIONS_BIN}/find-video-mkv-issues.sh" "$@"
  playsound-4
}

validate-video-files() {
  bash "${SHELL_FUNCTIONS_BIN}/validate-video-files.sh" "$@"
  playsound-2
}

scan-videos-audio-language() {
  bash "${SHELL_FUNCTIONS_BIN}/scan-videos-audio-language.sh" "$@"
  playsound-3
}

delete-duplicate-videos() {
  bash "${SHELL_FUNCTIONS_BIN}/delete-duplicate-videos.sh" "$@"
  playsound-6
}

remove-metadata() {
  bash "${SHELL_FUNCTIONS_BIN}/remove-metadata.sh" "$@"
  playsound-5
}

video-files-under() {
  bash "${SHELL_FUNCTIONS_BIN}/video-files-under.sh" "$@"
  playsound-4
}

video-list() {
  bash "${SHELL_FUNCTIONS_BIN}/video-list.sh" "$@"
  playsound-5
}

# -----------------------------------------------------------------------------
# Filesystem cleanup / utilities
# -----------------------------------------------------------------------------

delete-empty-folders() {
  bash "${SHELL_FUNCTIONS_BIN}/delete-empty-folders.sh" "$@"
  playsound-6
}

delete-smb-files() {
  bash "${SHELL_FUNCTIONS_BIN}/delete-smb-files.sh" "$@"
  playsound-6
}

delete-by-ext() {
  bash "${SHELL_FUNCTIONS_BIN}/delete-by-ext.sh" "$@"
  playsound-6
}

files-under-size() {
  bash "${SHELL_FUNCTIONS_BIN}/files-under-size.sh" "$@"
  playsound-4
}

find-largest-files() {
  bash "${SHELL_FUNCTIONS_BIN}/find-largest-files.sh" "$@"
  playsound-2
}

make-alpha-dir() {
  bash "${SHELL_FUNCTIONS_BIN}/make-alpha-dir.sh" "$@"
  playsound-4
}

remove-words() {
  bash "${SHELL_FUNCTIONS_BIN}/remove-words.sh" "$@"
}

compress-folders() {
  bash "${SHELL_FUNCTIONS_BIN}/compress-folders.sh" "$@"
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
  bash "${SHELL_FUNCTIONS_BIN}/find-movie-by-year.sh" "$@"
  playsound-2
}

# -----------------------------------------------------------------------------
# NAS / drives
# -----------------------------------------------------------------------------

mount-all-drives() {
  bash "${SHELL_FUNCTIONS_BIN}/mount-all-drives.sh"
  playsound-7
}

eject-all-drives() {
  bash "${SHELL_FUNCTIONS_BIN}/eject-all-drives.sh"
  playsound-7
}

ping-nas() {
  bash "${SHELL_FUNCTIONS_BIN}/ping-nas.sh"
}