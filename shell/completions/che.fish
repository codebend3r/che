# che 1.0.0 - generated file, do not edit.
#
# Generated from bin/commands.py by `che install`.
# To change a wrapper, edit that manifest and run `che install` again.

complete -c che -f
complete -c che -n __fish_use_subcommand -a all-actions -d 'GitHub Actions status for every open PR you authored'
complete -c che -n __fish_use_subcommand -a all-actions-watch -d 'Same as all-actions, refreshed on an interval'
complete -c che -n __fish_use_subcommand -a checkout-my-branches -d 'Check out recent remote branches you authored that aren\'t local yet'
complete -c che -n __fish_use_subcommand -a clean-stale-branches -d 'Delete local branches whose upstream is gone'
complete -c che -n __fish_use_subcommand -a clean-stale-branches-dr -d 'Delete local branches whose upstream is gone (preview)'
complete -c che -n __fish_use_subcommand -a prune-worktrees -d 'Remove every linked worktree, then prune stale admin records'
complete -c che -n __fish_use_subcommand -a prune-worktrees-dr -d 'Remove every linked worktree, then prune stale admin records (preview)'
complete -c che -n __fish_use_subcommand -a sync-all-branches -d 'Push every worktree, collapse the pushed ones, then tidy branches'
complete -c che -n __fish_use_subcommand -a sync-all-branches-dr -d 'Push every worktree, collapse the pushed ones, then tidy branches (preview)'
complete -c che -n __fish_use_subcommand -a update-from-origin -d 'Same as sync-all-branches but never pushes: fetch, collapse, rebase'
complete -c che -n __fish_use_subcommand -a update-local-branches -d 'Rebase every local branch that has an upstream onto origin'
complete -c che -n __fish_use_subcommand -a show-codecs -d 'Report media files outside the Direct Play codec/container set'
complete -c che -n __fish_use_subcommand -a fix-codecs -d 'Re-encode media to h265/aac mp4 so it Direct Plays'
complete -c che -n __fish_use_subcommand -a fix-codecs-dr -d 'Re-encode media to h265/aac mp4 so it Direct Plays (preview)'
complete -c che -n __fish_use_subcommand -a find-video-mkv-issues -d 'Scan MKV files and estimate Plex direct-play compatibility'
complete -c che -n __fish_use_subcommand -a validate-video-files -d 'Check .mp4/.mkv files decode by playing one frame with mpv'
complete -c che -n __fish_use_subcommand -a scan-videos-audio-language -d 'Print the audio language tags of every video under a path'
complete -c che -n __fish_use_subcommand -a remove-metadata -d 'Strip all metadata from video files recursively'
complete -c che -n __fish_use_subcommand -a rename-video-file -d 'Title-case video filenames (and optionally their folders)'
complete -c che -n __fish_use_subcommand -a delete-duplicate-videos -d 'Delete duplicate MKV/MP4 files under a root directory'
complete -c che -n __fish_use_subcommand -a delete-duplicate-videos-dr -d 'Delete duplicate MKV/MP4 files under a root directory (preview)'
complete -c che -n __fish_use_subcommand -a video-list -d 'List .mp4/.mkv files under a path with human-readable sizes'
complete -c che -n __fish_use_subcommand -a detect-green-magenta-videos -d 'Detect videos with the green/magenta chroma artifact'
complete -c che -n __fish_use_subcommand -a find-movie-by-year -d 'Find movie folders whose name ends with "(YYYY)"'
complete -c che -n __fish_use_subcommand -a largest-tv-shows -d 'Rank TV show folders in a library by total size on disk'
complete -c che -n __fish_use_subcommand -a delete-by-ext -d 'Delete files under a path matching a set of extensions'
complete -c che -n __fish_use_subcommand -a delete-by-ext-dr -d 'Delete files under a path matching a set of extensions (preview)'
complete -c che -n __fish_use_subcommand -a delete-empty-folders -d 'Delete truly-empty directories under a path, cascading upwards'
complete -c che -n __fish_use_subcommand -a delete-empty-folders-dr -d 'Delete truly-empty directories under a path, cascading upwards (preview)'
complete -c che -n __fish_use_subcommand -a delete-smb-files -d 'Delete .smbdelete* files left behind by an SMB share'
complete -c che -n __fish_use_subcommand -a delete-smb-files-dr -d 'Delete .smbdelete* files left behind by an SMB share (preview)'
complete -c che -n __fish_use_subcommand -a files-under-size -d 'Find video files at or under a size threshold'
complete -c che -n __fish_use_subcommand -a files-under-size-dr -d 'Find video files at or under a size threshold (preview)'
complete -c che -n __fish_use_subcommand -a find-largest-files -d 'List the largest files under a path, biggest first'
complete -c che -n __fish_use_subcommand -a make-alpha-dir -d 'Create \'#\' and A-Z bucket folders under a parent directory'
complete -c che -n __fish_use_subcommand -a compress-folders -d 'Zip every immediate subfolder of a path at max compression'
complete -c che -n __fish_use_subcommand -a list-permission -d 'Show ownership and mode of a volume under /Volumes'
complete -c che -n __fish_use_subcommand -a mount-all-drives -d 'Mount all NAS drives over SMB via AppleScript'
complete -c che -n __fish_use_subcommand -a eject-all-drives -d 'Eject all NAS volumes from /Volumes'
complete -c che -n __fish_use_subcommand -a eject-all-drives-dr -d 'Eject all NAS volumes from /Volumes (preview)'
complete -c che -n __fish_use_subcommand -a ping-nas -d 'Keep-alive pinger that remounts a NAS drive that dropped off'
complete -c che -n __fish_use_subcommand -a update-brew -d 'Update Homebrew, upgrade formulae and casks, then clean up'
complete -c che -n __fish_use_subcommand -a update-brew-dr -d 'Update Homebrew, upgrade formulae and casks, then clean up (preview)'
complete -c che -n __fish_use_subcommand -a btop -d 'Launch btop with a gruvbox theme matching the macOS appearance'
complete -c che -n __fish_use_subcommand -a install -d 'Install the shell wrappers into your shell startup files'
complete -c che -n __fish_use_subcommand -a update -d 'Pull the latest scripts and refresh the installed wrappers'
complete -c che -n __fish_use_subcommand -a doctor -d 'Check the install, the interpreter and every external tool'
complete -c che -n __fish_use_subcommand -a uninstall -d 'Remove the wrappers, the shim and the completions'
complete -c che -n __fish_use_subcommand -a list -d 'List every command, one per line'
complete -c che -n __fish_use_subcommand -a completions -d 'Print the completion script for a shell'

complete -c che -n "__fish_seen_subcommand_from all-actions" -l owner -r
complete -c che -n "__fish_seen_subcommand_from all-actions" -l author -r
complete -c che -n "__fish_seen_subcommand_from all-actions" -l pr-limit -r
complete -c che -n "__fish_seen_subcommand_from all-actions" -l interval -r
complete -c che -n "__fish_seen_subcommand_from all-actions" -l watch
complete -c che -n "__fish_seen_subcommand_from all-actions-watch" -l owner -r
complete -c che -n "__fish_seen_subcommand_from all-actions-watch" -l author -r
complete -c che -n "__fish_seen_subcommand_from all-actions-watch" -l pr-limit -r
complete -c che -n "__fish_seen_subcommand_from all-actions-watch" -l interval -r
complete -c che -n "__fish_seen_subcommand_from checkout-my-branches" -l author -r
complete -c che -n "__fish_seen_subcommand_from checkout-my-branches" -l limit -r
complete -c che -n "__fish_seen_subcommand_from clean-stale-branches" -l dry-run
complete -c che -n "__fish_seen_subcommand_from clean-stale-branches" -l protect -r
complete -c che -n "__fish_seen_subcommand_from clean-stale-branches-dr" -l dry-run
complete -c che -n "__fish_seen_subcommand_from clean-stale-branches-dr" -l protect -r
complete -c che -n "__fish_seen_subcommand_from prune-worktrees" -l dry-run
complete -c che -n "__fish_seen_subcommand_from prune-worktrees" -l force
complete -c che -n "__fish_seen_subcommand_from prune-worktrees-dr" -l dry-run
complete -c che -n "__fish_seen_subcommand_from prune-worktrees-dr" -l force
complete -c che -n "__fish_seen_subcommand_from sync-all-branches" -l dry-run
complete -c che -n "__fish_seen_subcommand_from sync-all-branches" -l no-push
complete -c che -n "__fish_seen_subcommand_from sync-all-branches" -l keep-locked
complete -c che -n "__fish_seen_subcommand_from sync-all-branches" -l author -r
complete -c che -n "__fish_seen_subcommand_from sync-all-branches" -l limit -r
complete -c che -n "__fish_seen_subcommand_from sync-all-branches-dr" -l dry-run
complete -c che -n "__fish_seen_subcommand_from sync-all-branches-dr" -l no-push
complete -c che -n "__fish_seen_subcommand_from sync-all-branches-dr" -l keep-locked
complete -c che -n "__fish_seen_subcommand_from sync-all-branches-dr" -l author -r
complete -c che -n "__fish_seen_subcommand_from sync-all-branches-dr" -l limit -r
complete -c che -n "__fish_seen_subcommand_from update-from-origin" -l dry-run
complete -c che -n "__fish_seen_subcommand_from update-from-origin" -l keep-locked
complete -c che -n "__fish_seen_subcommand_from update-from-origin" -l author -r
complete -c che -n "__fish_seen_subcommand_from update-from-origin" -l limit -r
complete -c che -n "__fish_seen_subcommand_from update-local-branches" -l limit -r
complete -c che -n "__fish_seen_subcommand_from update-local-branches" -l dry-run
complete -c che -n "__fish_seen_subcommand_from show-codecs" -l path -r -F
complete -c che -n "__fish_seen_subcommand_from show-codecs" -l verbose
complete -c che -n "__fish_seen_subcommand_from fix-codecs" -l path -r -F
complete -c che -n "__fish_seen_subcommand_from fix-codecs" -l delete-original
complete -c che -n "__fish_seen_subcommand_from fix-codecs" -l dry-run
complete -c che -n "__fish_seen_subcommand_from fix-codecs-dr" -l path -r -F
complete -c che -n "__fish_seen_subcommand_from fix-codecs-dr" -l delete-original
complete -c che -n "__fish_seen_subcommand_from fix-codecs-dr" -l dry-run
complete -c che -n "__fish_seen_subcommand_from find-video-mkv-issues" -l path -r -F
complete -c che -n "__fish_seen_subcommand_from find-video-mkv-issues" -l recursive
complete -c che -n "__fish_seen_subcommand_from validate-video-files" -l path -r -F
complete -c che -n "__fish_seen_subcommand_from validate-video-files" -l verbose
complete -c che -n "__fish_seen_subcommand_from scan-videos-audio-language" -l -
complete -c che -n "__fish_seen_subcommand_from scan-videos-audio-language" -l -
complete -c che -n "__fish_seen_subcommand_from scan-videos-audio-language" -l p
complete -c che -n "__fish_seen_subcommand_from scan-videos-audio-language" -l a
complete -c che -n "__fish_seen_subcommand_from scan-videos-audio-language" -l t
complete -c che -n "__fish_seen_subcommand_from scan-videos-audio-language" -l h
complete -c che -n "__fish_seen_subcommand_from remove-metadata" -l path -r -F
complete -c che -n "__fish_seen_subcommand_from remove-metadata" -l exts -r
complete -c che -n "__fish_seen_subcommand_from rename-video-file" -l path -r -F
complete -c che -n "__fish_seen_subcommand_from rename-video-file" -l recursive
complete -c che -n "__fish_seen_subcommand_from rename-video-file" -l rename-folders
complete -c che -n "__fish_seen_subcommand_from rename-video-file" -l capitalize-preps
complete -c che -n "__fish_seen_subcommand_from rename-video-file" -l dry-run
complete -c che -n "__fish_seen_subcommand_from rename-video-file" -l ignore-words -r
complete -c che -n "__fish_seen_subcommand_from delete-duplicate-videos" -l path -r -F
complete -c che -n "__fish_seen_subcommand_from delete-duplicate-videos" -l strategy -r
complete -c che -n "__fish_seen_subcommand_from delete-duplicate-videos" -l dry-run
complete -c che -n "__fish_seen_subcommand_from delete-duplicate-videos" -l verbose
complete -c che -n "__fish_seen_subcommand_from delete-duplicate-videos-dr" -l path -r -F
complete -c che -n "__fish_seen_subcommand_from delete-duplicate-videos-dr" -l strategy -r
complete -c che -n "__fish_seen_subcommand_from delete-duplicate-videos-dr" -l dry-run
complete -c che -n "__fish_seen_subcommand_from delete-duplicate-videos-dr" -l verbose
complete -c che -n "__fish_seen_subcommand_from video-list" -l path -r -F
complete -c che -n "__fish_seen_subcommand_from video-list" -l recursive
complete -c che -n "__fish_seen_subcommand_from video-list" -l with-folder
complete -c che -n "__fish_seen_subcommand_from video-list" -l sort -r
complete -c che -n "__fish_seen_subcommand_from detect-green-magenta-videos" -l samples -r
complete -c che -n "__fish_seen_subcommand_from detect-green-magenta-videos" -l threshold -r
complete -c che -n "__fish_seen_subcommand_from detect-green-magenta-videos" -l verbose
complete -c che -n "__fish_seen_subcommand_from find-movie-by-year" -l year -r
complete -c che -n "__fish_seen_subcommand_from find-movie-by-year" -l path -r -F
complete -c che -n "__fish_seen_subcommand_from largest-tv-shows" -l path -r -F
complete -c che -n "__fish_seen_subcommand_from largest-tv-shows" -l limit -r
complete -c che -n "__fish_seen_subcommand_from largest-tv-shows" -l full-path
complete -c che -n "__fish_seen_subcommand_from largest-tv-shows" -l debug
complete -c che -n "__fish_seen_subcommand_from delete-by-ext" -l path -r -F
complete -c che -n "__fish_seen_subcommand_from delete-by-ext" -l ext -r
complete -c che -n "__fish_seen_subcommand_from delete-by-ext" -l dry-run
complete -c che -n "__fish_seen_subcommand_from delete-by-ext" -l verbose
complete -c che -n "__fish_seen_subcommand_from delete-by-ext-dr" -l path -r -F
complete -c che -n "__fish_seen_subcommand_from delete-by-ext-dr" -l ext -r
complete -c che -n "__fish_seen_subcommand_from delete-by-ext-dr" -l dry-run
complete -c che -n "__fish_seen_subcommand_from delete-by-ext-dr" -l verbose
complete -c che -n "__fish_seen_subcommand_from delete-empty-folders" -l path -r -F
complete -c che -n "__fish_seen_subcommand_from delete-empty-folders" -l dry-run
complete -c che -n "__fish_seen_subcommand_from delete-empty-folders" -l verbose
complete -c che -n "__fish_seen_subcommand_from delete-empty-folders-dr" -l path -r -F
complete -c che -n "__fish_seen_subcommand_from delete-empty-folders-dr" -l dry-run
complete -c che -n "__fish_seen_subcommand_from delete-empty-folders-dr" -l verbose
complete -c che -n "__fish_seen_subcommand_from delete-smb-files" -l path -r -F
complete -c che -n "__fish_seen_subcommand_from delete-smb-files" -l dry-run
complete -c che -n "__fish_seen_subcommand_from delete-smb-files-dr" -l path -r -F
complete -c che -n "__fish_seen_subcommand_from delete-smb-files-dr" -l dry-run
complete -c che -n "__fish_seen_subcommand_from files-under-size" -l path -r -F
complete -c che -n "__fish_seen_subcommand_from files-under-size" -l size -r
complete -c che -n "__fish_seen_subcommand_from files-under-size" -l dry-run
complete -c che -n "__fish_seen_subcommand_from files-under-size-dr" -l path -r -F
complete -c che -n "__fish_seen_subcommand_from files-under-size-dr" -l size -r
complete -c che -n "__fish_seen_subcommand_from files-under-size-dr" -l dry-run
complete -c che -n "__fish_seen_subcommand_from find-largest-files" -l path -r -F
complete -c che -n "__fish_seen_subcommand_from find-largest-files" -l length -r
complete -c che -n "__fish_seen_subcommand_from find-largest-files" -l full-path
complete -c che -n "__fish_seen_subcommand_from make-alpha-dir" -l -
complete -c che -n "__fish_seen_subcommand_from make-alpha-dir" -l -
complete -c che -n "__fish_seen_subcommand_from make-alpha-dir" -l p
complete -c che -n "__fish_seen_subcommand_from make-alpha-dir" -l a
complete -c che -n "__fish_seen_subcommand_from make-alpha-dir" -l t
complete -c che -n "__fish_seen_subcommand_from make-alpha-dir" -l h
complete -c che -n "__fish_seen_subcommand_from compress-folders" -l path -r -F
complete -c che -n "__fish_seen_subcommand_from compress-folders" -l dry-run
complete -c che -n "__fish_seen_subcommand_from compress-folders" -l verbose
complete -c che -n "__fish_seen_subcommand_from mount-all-drives" -l only -r
complete -c che -n "__fish_seen_subcommand_from mount-all-drives" -l use-ip
complete -c che -n "__fish_seen_subcommand_from mount-all-drives" -l quiet
complete -c che -n "__fish_seen_subcommand_from eject-all-drives" -l dry-run
complete -c che -n "__fish_seen_subcommand_from eject-all-drives" -l only -r
complete -c che -n "__fish_seen_subcommand_from eject-all-drives" -l no-force
complete -c che -n "__fish_seen_subcommand_from eject-all-drives" -l no-clear-favorites
complete -c che -n "__fish_seen_subcommand_from eject-all-drives" -l quiet
complete -c che -n "__fish_seen_subcommand_from eject-all-drives-dr" -l dry-run
complete -c che -n "__fish_seen_subcommand_from eject-all-drives-dr" -l only -r
complete -c che -n "__fish_seen_subcommand_from eject-all-drives-dr" -l no-force
complete -c che -n "__fish_seen_subcommand_from eject-all-drives-dr" -l no-clear-favorites
complete -c che -n "__fish_seen_subcommand_from eject-all-drives-dr" -l quiet
complete -c che -n "__fish_seen_subcommand_from ping-nas" -l interval -r
complete -c che -n "__fish_seen_subcommand_from ping-nas" -l ping-timeout -r
complete -c che -n "__fish_seen_subcommand_from ping-nas" -l only -r
complete -c che -n "__fish_seen_subcommand_from ping-nas" -l no-remount
complete -c che -n "__fish_seen_subcommand_from ping-nas" -l use-ip
complete -c che -n "__fish_seen_subcommand_from ping-nas" -l once
complete -c che -n "__fish_seen_subcommand_from ping-nas" -l quiet
complete -c che -n "__fish_seen_subcommand_from update-brew" -l dry-run
complete -c che -n "__fish_seen_subcommand_from update-brew" -l no-cask
complete -c che -n "__fish_seen_subcommand_from update-brew" -l no-cleanup
complete -c che -n "__fish_seen_subcommand_from update-brew-dr" -l dry-run
complete -c che -n "__fish_seen_subcommand_from update-brew-dr" -l no-cask
complete -c che -n "__fish_seen_subcommand_from update-brew-dr" -l no-cleanup
complete -c che -n "__fish_seen_subcommand_from install" -l shells -r
complete -c che -n "__fish_seen_subcommand_from install" -l all-shells
complete -c che -n "__fish_seen_subcommand_from install" -l yes
complete -c che -n "__fish_seen_subcommand_from install" -l dry-run
complete -c che -n "__fish_seen_subcommand_from install" -l no-completions
complete -c che -n "__fish_seen_subcommand_from install" -l no-path-shim
complete -c che -n "__fish_seen_subcommand_from install" -l replace-legacy
complete -c che -n "__fish_seen_subcommand_from install" -l print
complete -c che -n "__fish_seen_subcommand_from update" -l check
complete -c che -n "__fish_seen_subcommand_from update" -l yes
complete -c che -n "__fish_seen_subcommand_from doctor" -l json
complete -c che -n "__fish_seen_subcommand_from doctor" -l verbose
complete -c che -n "__fish_seen_subcommand_from uninstall" -l yes
complete -c che -n "__fish_seen_subcommand_from uninstall" -l dry-run
complete -c che -n "__fish_seen_subcommand_from uninstall" -l purge
complete -c che -n "__fish_seen_subcommand_from list" -l category -r
complete -c che -n "__fish_seen_subcommand_from list" -l json
complete -c che -n "__fish_seen_subcommand_from list" -l dry
complete -c che -n "__fish_seen_subcommand_from completions" -l -
complete -c che -n "__fish_seen_subcommand_from completions" -l -
complete -c che -n "__fish_seen_subcommand_from completions" -l s
complete -c che -n "__fish_seen_subcommand_from completions" -l h
complete -c che -n "__fish_seen_subcommand_from completions" -l e
complete -c che -n "__fish_seen_subcommand_from completions" -l l
complete -c che -n "__fish_seen_subcommand_from completions" -l l

complete -c all-actions -l owner -r
complete -c all-actions -l author -r
complete -c all-actions -l pr-limit -r
complete -c all-actions -l interval -r
complete -c all-actions -l watch
complete -c all-actions-watch -l owner -r
complete -c all-actions-watch -l author -r
complete -c all-actions-watch -l pr-limit -r
complete -c all-actions-watch -l interval -r
complete -c checkout-my-branches -l author -r
complete -c checkout-my-branches -l limit -r
complete -c clean-stale-branches -l dry-run
complete -c clean-stale-branches -l protect -r
complete -c clean-stale-branches-dr -l dry-run
complete -c clean-stale-branches-dr -l protect -r
complete -c prune-worktrees -l dry-run
complete -c prune-worktrees -l force
complete -c prune-worktrees-dr -l dry-run
complete -c prune-worktrees-dr -l force
complete -c sync-all-branches -l dry-run
complete -c sync-all-branches -l no-push
complete -c sync-all-branches -l keep-locked
complete -c sync-all-branches -l author -r
complete -c sync-all-branches -l limit -r
complete -c sync-all-branches-dr -l dry-run
complete -c sync-all-branches-dr -l no-push
complete -c sync-all-branches-dr -l keep-locked
complete -c sync-all-branches-dr -l author -r
complete -c sync-all-branches-dr -l limit -r
complete -c update-from-origin -l dry-run
complete -c update-from-origin -l keep-locked
complete -c update-from-origin -l author -r
complete -c update-from-origin -l limit -r
complete -c update-local-branches -l limit -r
complete -c update-local-branches -l dry-run
complete -c show-codecs -l path -r -F
complete -c show-codecs -l verbose
complete -c fix-codecs -l path -r -F
complete -c fix-codecs -l delete-original
complete -c fix-codecs -l dry-run
complete -c fix-codecs-dr -l path -r -F
complete -c fix-codecs-dr -l delete-original
complete -c fix-codecs-dr -l dry-run
complete -c find-video-mkv-issues -l path -r -F
complete -c find-video-mkv-issues -l recursive
complete -c validate-video-files -l path -r -F
complete -c validate-video-files -l verbose
complete -c scan-videos-audio-language -l -
complete -c scan-videos-audio-language -l -
complete -c scan-videos-audio-language -l p
complete -c scan-videos-audio-language -l a
complete -c scan-videos-audio-language -l t
complete -c scan-videos-audio-language -l h
complete -c remove-metadata -l path -r -F
complete -c remove-metadata -l exts -r
complete -c rename-video-file -l path -r -F
complete -c rename-video-file -l recursive
complete -c rename-video-file -l rename-folders
complete -c rename-video-file -l capitalize-preps
complete -c rename-video-file -l dry-run
complete -c rename-video-file -l ignore-words -r
complete -c delete-duplicate-videos -l path -r -F
complete -c delete-duplicate-videos -l strategy -r
complete -c delete-duplicate-videos -l dry-run
complete -c delete-duplicate-videos -l verbose
complete -c delete-duplicate-videos-dr -l path -r -F
complete -c delete-duplicate-videos-dr -l strategy -r
complete -c delete-duplicate-videos-dr -l dry-run
complete -c delete-duplicate-videos-dr -l verbose
complete -c video-list -l path -r -F
complete -c video-list -l recursive
complete -c video-list -l with-folder
complete -c video-list -l sort -r
complete -c detect-green-magenta-videos -l samples -r
complete -c detect-green-magenta-videos -l threshold -r
complete -c detect-green-magenta-videos -l verbose
complete -c find-movie-by-year -l year -r
complete -c find-movie-by-year -l path -r -F
complete -c largest-tv-shows -l path -r -F
complete -c largest-tv-shows -l limit -r
complete -c largest-tv-shows -l full-path
complete -c largest-tv-shows -l debug
complete -c delete-by-ext -l path -r -F
complete -c delete-by-ext -l ext -r
complete -c delete-by-ext -l dry-run
complete -c delete-by-ext -l verbose
complete -c delete-by-ext-dr -l path -r -F
complete -c delete-by-ext-dr -l ext -r
complete -c delete-by-ext-dr -l dry-run
complete -c delete-by-ext-dr -l verbose
complete -c delete-empty-folders -l path -r -F
complete -c delete-empty-folders -l dry-run
complete -c delete-empty-folders -l verbose
complete -c delete-empty-folders-dr -l path -r -F
complete -c delete-empty-folders-dr -l dry-run
complete -c delete-empty-folders-dr -l verbose
complete -c delete-smb-files -l path -r -F
complete -c delete-smb-files -l dry-run
complete -c delete-smb-files-dr -l path -r -F
complete -c delete-smb-files-dr -l dry-run
complete -c files-under-size -l path -r -F
complete -c files-under-size -l size -r
complete -c files-under-size -l dry-run
complete -c files-under-size-dr -l path -r -F
complete -c files-under-size-dr -l size -r
complete -c files-under-size-dr -l dry-run
complete -c find-largest-files -l path -r -F
complete -c find-largest-files -l length -r
complete -c find-largest-files -l full-path
complete -c make-alpha-dir -l -
complete -c make-alpha-dir -l -
complete -c make-alpha-dir -l p
complete -c make-alpha-dir -l a
complete -c make-alpha-dir -l t
complete -c make-alpha-dir -l h
complete -c compress-folders -l path -r -F
complete -c compress-folders -l dry-run
complete -c compress-folders -l verbose
complete -c mount-all-drives -l only -r
complete -c mount-all-drives -l use-ip
complete -c mount-all-drives -l quiet
complete -c eject-all-drives -l dry-run
complete -c eject-all-drives -l only -r
complete -c eject-all-drives -l no-force
complete -c eject-all-drives -l no-clear-favorites
complete -c eject-all-drives -l quiet
complete -c eject-all-drives-dr -l dry-run
complete -c eject-all-drives-dr -l only -r
complete -c eject-all-drives-dr -l no-force
complete -c eject-all-drives-dr -l no-clear-favorites
complete -c eject-all-drives-dr -l quiet
complete -c ping-nas -l interval -r
complete -c ping-nas -l ping-timeout -r
complete -c ping-nas -l only -r
complete -c ping-nas -l no-remount
complete -c ping-nas -l use-ip
complete -c ping-nas -l once
complete -c ping-nas -l quiet
complete -c update-brew -l dry-run
complete -c update-brew -l no-cask
complete -c update-brew -l no-cleanup
complete -c update-brew-dr -l dry-run
complete -c update-brew-dr -l no-cask
complete -c update-brew-dr -l no-cleanup
