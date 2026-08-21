# che 1.0.0 - generated file, do not edit.
#
# Generated from bin/commands.py by `che install`.
# To change a wrapper, edit that manifest and run `che install` again.
# shellcheck shell=bash

_che_flags_for() {
  case "$1" in
    all-actions) echo "--owner= --author= --pr-limit= --interval= --watch --help" ;;
    all-actions-watch) echo "--owner= --author= --pr-limit= --interval= --help" ;;
    checkout-my-branches) echo "--author= --limit= --help" ;;
    clean-stale-branches) echo "--dry-run --protect= --help" ;;
    clean-stale-branches-dr) echo "--dry-run --protect= --help" ;;
    prune-worktrees) echo "--dry-run --force --help" ;;
    prune-worktrees-dr) echo "--dry-run --force --help" ;;
    sync-all-branches) echo "--dry-run --no-push --keep-locked --author= --limit= --help" ;;
    sync-all-branches-dr) echo "--dry-run --no-push --keep-locked --author= --limit= --help" ;;
    update-from-origin) echo "--dry-run --keep-locked --author= --limit= --help" ;;
    update-local-branches) echo "--limit= --dry-run --help" ;;
    show-codecs) echo "--path= --verbose --help" ;;
    fix-codecs) echo "--path= --delete-original --dry-run --help" ;;
    fix-codecs-dr) echo "--path= --delete-original --dry-run --help" ;;
    find-video-mkv-issues) echo "--path= --recursive --help" ;;
    validate-video-files) echo "--path= --verbose --help" ;;
    scan-videos-audio-language) echo "- - p a t h --help" ;;
    remove-metadata) echo "--path= --exts= --help" ;;
    rename-video-file) echo "--path= --recursive --rename-folders --capitalize-preps --dry-run --ignore-words= --help" ;;
    delete-duplicate-videos) echo "--path= --strategy= --dry-run --verbose --help" ;;
    delete-duplicate-videos-dr) echo "--path= --strategy= --dry-run --verbose --help" ;;
    video-list) echo "--path= --recursive --with-folder --sort= --help" ;;
    detect-green-magenta-videos) echo "--samples= --threshold= --verbose --help" ;;
    find-movie-by-year) echo "--year= --path= --help" ;;
    largest-tv-shows) echo "--path= --limit= --full-path --debug --help" ;;
    delete-by-ext) echo "--path= --ext= --dry-run --verbose --help" ;;
    delete-by-ext-dr) echo "--path= --ext= --dry-run --verbose --help" ;;
    delete-empty-folders) echo "--path= --dry-run --verbose --help" ;;
    delete-empty-folders-dr) echo "--path= --dry-run --verbose --help" ;;
    delete-smb-files) echo "--path= --dry-run --help" ;;
    delete-smb-files-dr) echo "--path= --dry-run --help" ;;
    files-under-size) echo "--path= --size= --dry-run --help" ;;
    files-under-size-dr) echo "--path= --size= --dry-run --help" ;;
    find-largest-files) echo "--path= --length= --full-path --help" ;;
    make-alpha-dir) echo "- - p a t h --help" ;;
    compress-folders) echo "--path= --dry-run --verbose --help" ;;
    list-permission) echo "--help" ;;
    mount-all-drives) echo "--only= --use-ip --quiet --help" ;;
    eject-all-drives) echo "--dry-run --only= --no-force --no-clear-favorites --quiet --help" ;;
    eject-all-drives-dr) echo "--dry-run --only= --no-force --no-clear-favorites --quiet --help" ;;
    ping-nas) echo "--interval= --ping-timeout= --only= --no-remount --use-ip --once --quiet --help" ;;
    update-brew) echo "--dry-run --no-cask --no-cleanup --help" ;;
    update-brew-dr) echo "--dry-run --no-cask --no-cleanup --help" ;;
    btop) echo "--help" ;;
    install) echo "--shells= --all-shells --yes --dry-run --no-completions --no-path-shim --replace-legacy --print --help" ;;
    update) echo "--check --yes --help" ;;
    doctor) echo "--json --verbose --help" ;;
    uninstall) echo "--yes --dry-run --purge --help" ;;
    list) echo "--category= --json --dry --help" ;;
    completions) echo "- - s h e l l --help" ;;
    *) echo "--help" ;;
  esac
}

# `mapfile` is bash 4+, and macOS still ships bash 3.2, so read the candidates
# a line at a time instead - which also keeps filenames with spaces intact.
_che_reply() {
  local prefix="$1" line
  COMPREPLY=()
  while IFS= read -r line; do
    COMPREPLY+=( "$prefix$line" )
  done
}

_che_complete_for() {
  local cmd="$1" cur="$2" prefix value

  case "$cur" in
    *=*)
      prefix="${cur%%=*}="
      value="${cur#*=}"
      _che_reply "$prefix" < <(compgen -f -- "$value")
      ;;
    -*)
      _che_reply "" < <(compgen -W "$(_che_flags_for "$cmd")" -- "$cur")
      ;;
    *)
      _che_reply "" < <(compgen -f -- "$cur")
      ;;
  esac
}

_che_complete() {
  local cur="${COMP_WORDS[COMP_CWORD]}"

  if [ "$COMP_CWORD" -eq 1 ]; then
    _che_reply "" < <(compgen -W "all-actions all-actions-watch checkout-my-branches clean-stale-branches clean-stale-branches-dr prune-worktrees prune-worktrees-dr sync-all-branches sync-all-branches-dr update-from-origin update-local-branches show-codecs fix-codecs fix-codecs-dr find-video-mkv-issues validate-video-files scan-videos-audio-language remove-metadata rename-video-file delete-duplicate-videos delete-duplicate-videos-dr video-list detect-green-magenta-videos find-movie-by-year largest-tv-shows delete-by-ext delete-by-ext-dr delete-empty-folders delete-empty-folders-dr delete-smb-files delete-smb-files-dr files-under-size files-under-size-dr find-largest-files make-alpha-dir compress-folders list-permission mount-all-drives eject-all-drives eject-all-drives-dr ping-nas update-brew update-brew-dr btop install update doctor uninstall list completions" -- "$cur")
    return
  fi

  _che_complete_for "${COMP_WORDS[1]}" "$cur"
}

_che_complete_wrapper() {
  _che_complete_for "${COMP_WORDS[0]}" "${COMP_WORDS[COMP_CWORD]}"
}

complete -o nospace -F _che_complete che
complete -o nospace -F _che_complete_wrapper all-actions all-actions-watch checkout-my-branches clean-stale-branches clean-stale-branches-dr prune-worktrees prune-worktrees-dr sync-all-branches sync-all-branches-dr update-from-origin update-local-branches show-codecs fix-codecs fix-codecs-dr find-video-mkv-issues validate-video-files scan-videos-audio-language remove-metadata rename-video-file delete-duplicate-videos delete-duplicate-videos-dr video-list detect-green-magenta-videos find-movie-by-year largest-tv-shows delete-by-ext delete-by-ext-dr delete-empty-folders delete-empty-folders-dr delete-smb-files delete-smb-files-dr files-under-size files-under-size-dr find-largest-files make-alpha-dir compress-folders list-permission mount-all-drives eject-all-drives eject-all-drives-dr ping-nas update-brew update-brew-dr btop
