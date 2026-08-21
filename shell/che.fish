# che 1.0.0 - generated file, do not edit.
#
# Generated from bin/commands.py by `che install`.
# To change a wrapper, edit that manifest and run `che install` again.

if not set -q CHE_HOME
    set -l __che_dir (dirname (status --current-filename))/..
    if type -q path
        set -gx CHE_HOME (path resolve $__che_dir)
    else
        set -gx CHE_HOME $__che_dir
    end
    set -e __che_dir
end
set -g CHE_BIN "$CHE_HOME/bin"
if not set -q CHE_PYTHON
    set -gx CHE_PYTHON python3
end
set -gx SHELL_FUNCTIONS_BIN "$CHE_BIN"

# Play a wrapper's completion sound, then return the status it was given.
function che_notify --description 'che: completion sound'
    set -l code 0
    if set -q argv[2]
        set code $argv[2]
    end
    if test "$CHE_SOUNDS" != "0"
        if type -q "playsound-$argv[1]"
            "playsound-$argv[1]" >/dev/null 2>&1
        end
    end
    return $code
end

function che --description 'che: shell helpers dispatcher'
    if test (count $argv) -eq 0
        "$CHE_PYTHON" "$CHE_BIN/che.py"
    else
        "$CHE_PYTHON" "$CHE_BIN/che.py" $argv
        che_notify 7 $status
    end
end

# --------------------------------------------------------------------------
# Git - Branch hygiene, worktrees and GitHub Actions
# --------------------------------------------------------------------------

function all-actions --description 'GitHub Actions status for every open PR you authored'
    "$CHE_PYTHON" "$CHE_BIN/git/all-actions.py" $argv
end

function all-actions-watch --description 'Same as all-actions, refreshed on an interval'
    "$CHE_PYTHON" "$CHE_BIN/git/all-actions.py" --watch $argv
end

function checkout-my-branches --description 'Check out recent remote branches you authored that aren\'t local yet'
    "$CHE_PYTHON" "$CHE_BIN/git/checkout-my-branches.py" $argv
    che_notify 7 $status
end

function clean-stale-branches --description 'Delete local branches whose upstream is gone'
    env DRY_RUN=false "$CHE_PYTHON" "$CHE_BIN/git/clean-stale-branches.py" $argv
    che_notify 4 $status
end

function clean-stale-branches-dr --description 'Delete local branches whose upstream is gone (preview only)'
    env DRY_RUN=true "$CHE_PYTHON" "$CHE_BIN/git/clean-stale-branches.py" $argv
    che_notify 7 $status
end

function prune-worktrees --description 'Remove every linked worktree, then prune stale admin records'
    env DRY_RUN=false "$CHE_PYTHON" "$CHE_BIN/git/prune-worktrees.py" $argv
    che_notify 4 $status
end

function prune-worktrees-dr --description 'Remove every linked worktree, then prune stale admin records (preview only)'
    env DRY_RUN=true "$CHE_PYTHON" "$CHE_BIN/git/prune-worktrees.py" $argv
    che_notify 7 $status
end

function sync-all-branches --description 'Push every worktree, collapse the pushed ones, then tidy branches'
    env DRY_RUN=false "$CHE_PYTHON" "$CHE_BIN/git/sync-all-branches.py" $argv
    che_notify 7 $status
end

function sync-all-branches-dr --description 'Push every worktree, collapse the pushed ones, then tidy branches (preview only)'
    env DRY_RUN=true "$CHE_PYTHON" "$CHE_BIN/git/sync-all-branches.py" $argv
    che_notify 7 $status
end

function update-from-origin --description 'Same as sync-all-branches but never pushes: fetch, collapse, rebase'
    env DRY_RUN=false "$CHE_PYTHON" "$CHE_BIN/git/sync-all-branches.py" --no-push $argv
    che_notify 7 $status
end

function update-local-branches --description 'Rebase every local branch that has an upstream onto origin'
    "$CHE_PYTHON" "$CHE_BIN/git/update-local-branches.py" $argv
    che_notify 5 $status
end

# --------------------------------------------------------------------------
# Video - Codecs, renaming, dedupe and metadata
# --------------------------------------------------------------------------

function show-codecs --description 'Report media files outside the Direct Play codec/container set'
    "$CHE_PYTHON" "$CHE_BIN/video/show-codecs.py" $argv
    che_notify 6 $status
end

function fix-codecs --description 'Re-encode media to h265/aac mp4 so it Direct Plays'
    env DRY_RUN=false "$CHE_PYTHON" "$CHE_BIN/video/fix-codecs.py" $argv
    che_notify 7 $status
end

function fix-codecs-dr --description 'Re-encode media to h265/aac mp4 so it Direct Plays (preview only)'
    env DRY_RUN=true "$CHE_PYTHON" "$CHE_BIN/video/fix-codecs.py" $argv
    che_notify 7 $status
end

function find-video-mkv-issues --description 'Scan MKV files and estimate Plex direct-play compatibility'
    "$CHE_PYTHON" "$CHE_BIN/video/find-video-mkv-issues.py" $argv
    che_notify 4 $status
end

function validate-video-files --description 'Check .mp4/.mkv files decode by playing one frame with mpv'
    "$CHE_PYTHON" "$CHE_BIN/video/validate-video-files.py" $argv
    che_notify 2 $status
end

function scan-videos-audio-language --description 'Print the audio language tags of every video under a path'
    "$CHE_PYTHON" "$CHE_BIN/video/scan-videos-audio-language.py" $argv
    che_notify 3 $status
end

function remove-metadata --description 'Strip all metadata from video files recursively'
    "$CHE_PYTHON" "$CHE_BIN/video/remove-metadata.py" $argv
    che_notify 4 $status
end

function rename-video-file --description 'Title-case video filenames (and optionally their folders)'
    "$CHE_PYTHON" "$CHE_BIN/video/rename-video-file.py" $argv
    che_notify 5 $status
end

function delete-duplicate-videos --description 'Delete duplicate MKV/MP4 files under a root directory'
    env DRY_RUN=false "$CHE_PYTHON" "$CHE_BIN/video/delete-duplicate-videos.py" $argv
    che_notify 6 $status
end

function delete-duplicate-videos-dr --description 'Delete duplicate MKV/MP4 files under a root directory (preview only)'
    env DRY_RUN=true "$CHE_PYTHON" "$CHE_BIN/video/delete-duplicate-videos.py" $argv
    che_notify 6 $status
end

function video-list --description 'List .mp4/.mkv files under a path with human-readable sizes'
    "$CHE_PYTHON" "$CHE_BIN/video/video-list.py" $argv
    che_notify 5 $status
end

function detect-green-magenta-videos --description 'Detect videos with the green/magenta chroma artifact'
    "$CHE_PYTHON" "$CHE_BIN/video/detect-green-magenta-videos.py" $argv
    che_notify 3 $status
end

function find-movie-by-year --description 'Find movie folders whose name ends with "(YYYY)"'
    "$CHE_PYTHON" "$CHE_BIN/video/find-movie-by-year.py" $argv
    che_notify 2 $status
end

function largest-tv-shows --description 'Rank TV show folders in a library by total size on disk'
    "$CHE_PYTHON" "$CHE_BIN/video/largest-tv-shows.py" $argv
    che_notify 2 $status
end

# --------------------------------------------------------------------------
# Files - Delete, compress and inspect by size or extension
# --------------------------------------------------------------------------

function delete-by-ext --description 'Delete files under a path matching a set of extensions'
    env DRY_RUN=false "$CHE_PYTHON" "$CHE_BIN/files/delete-by-ext.py" $argv
    che_notify 6 $status
end

function delete-by-ext-dr --description 'Delete files under a path matching a set of extensions (preview only)'
    env DRY_RUN=true "$CHE_PYTHON" "$CHE_BIN/files/delete-by-ext.py" $argv
    che_notify 7 $status
end

function delete-empty-folders --description 'Delete truly-empty directories under a path, cascading upwards'
    env DRY_RUN=false "$CHE_PYTHON" "$CHE_BIN/files/delete-empty-folders.py" $argv
    che_notify 6 $status
end

function delete-empty-folders-dr --description 'Delete truly-empty directories under a path, cascading upwards (preview only)'
    env DRY_RUN=true "$CHE_PYTHON" "$CHE_BIN/files/delete-empty-folders.py" $argv
    che_notify 7 $status
end

function delete-smb-files --description 'Delete .smbdelete* files left behind by an SMB share'
    env DRY_RUN=false "$CHE_PYTHON" "$CHE_BIN/files/delete-smb-files.py" $argv
    che_notify 6 $status
end

function delete-smb-files-dr --description 'Delete .smbdelete* files left behind by an SMB share (preview only)'
    env DRY_RUN=true "$CHE_PYTHON" "$CHE_BIN/files/delete-smb-files.py" $argv
    che_notify 7 $status
end

function files-under-size --description 'Find video files at or under a size threshold'
    env DRY_RUN=false "$CHE_PYTHON" "$CHE_BIN/files/files-under-size.py" $argv
    che_notify 4 $status
end

function files-under-size-dr --description 'Find video files at or under a size threshold (preview only)'
    env DRY_RUN=true "$CHE_PYTHON" "$CHE_BIN/files/files-under-size.py" $argv
    che_notify 7 $status
end

function find-largest-files --description 'List the largest files under a path, biggest first'
    "$CHE_PYTHON" "$CHE_BIN/files/find-largest-files.py" $argv
    che_notify 2 $status
end

function make-alpha-dir --description 'Create \'#\' and A-Z bucket folders under a parent directory'
    "$CHE_PYTHON" "$CHE_BIN/files/make-alpha-dir.py" $argv
    che_notify 4 $status
end

function compress-folders --description 'Zip every immediate subfolder of a path at max compression'
    "$CHE_PYTHON" "$CHE_BIN/files/compress-folders.py" $argv
    che_notify 7 $status
end

function list-permission --description 'Show ownership and mode of a volume under /Volumes'
    ls -ld "/Volumes/$argv[1]"
    che_notify 7 $status
end

# --------------------------------------------------------------------------
# Drives - Mount, eject and keep-alive for the NAS volumes
# --------------------------------------------------------------------------

function mount-all-drives --description 'Mount all NAS drives over SMB via AppleScript'
    "$CHE_PYTHON" "$CHE_BIN/drives/mount-all-drives.py" $argv
    che_notify 7 $status
end

function eject-all-drives --description 'Eject all NAS volumes from /Volumes'
    "$CHE_PYTHON" "$CHE_BIN/drives/eject-all-drives.py" $argv
    che_notify 7 $status
end

function eject-all-drives-dr --description 'Eject all NAS volumes from /Volumes (preview only)'
    "$CHE_PYTHON" "$CHE_BIN/drives/eject-all-drives.py" --dry-run $argv
    che_notify 7 $status
end

function ping-nas --description 'Keep-alive pinger that remounts a NAS drive that dropped off'
    "$CHE_PYTHON" "$CHE_BIN/drives/ping-nas.py" $argv
end

# --------------------------------------------------------------------------
# System - Homebrew, monitoring and the machine itself
# --------------------------------------------------------------------------

function update-brew --description 'Update Homebrew, upgrade formulae and casks, then clean up'
    "$CHE_PYTHON" "$CHE_BIN/system/update-brew.py" $argv
    che_notify 7 $status
end

function update-brew-dr --description 'Update Homebrew, upgrade formulae and casks, then clean up (preview only)'
    "$CHE_PYTHON" "$CHE_BIN/system/update-brew.py" --dry-run $argv
    che_notify 7 $status
end

function btop --description 'Launch btop with a gruvbox theme matching the macOS appearance'
    "$CHE_PYTHON" "$CHE_BIN/system/btop-launch.py" $argv
end

if test -r "$CHE_HOME/shell/completions/che.fish"
    source "$CHE_HOME/shell/completions/che.fish"
end
