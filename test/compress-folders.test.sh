#!/usr/bin/env bash

# Tests for bin/files/compress-folders.sh
# Run: bash test/compress-folders.test.sh

set -uo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SUT="$SCRIPT_DIR/../bin/files/compress-folders.sh"

if ! command -v zip >/dev/null 2>&1; then
  echo "⚠️  'zip' not installed — skipping compress-folders tests"
  exit 0
fi
if ! command -v unzip >/dev/null 2>&1; then
  echo "⚠️  'unzip' not installed — skipping compress-folders tests"
  exit 0
fi

pass=0
fail=0
failures=()

assert_exists() {
  [[ -e "$1" ]] && return 0
  failures+=("$2 — expected to exist: $1")
  return 1
}
assert_missing() {
  [[ ! -e "$1" ]] && return 0
  failures+=("$2 — expected NOT to exist: $1")
  return 1
}
assert_zip_contains() {
  local zip=$1 path=$2 msg=$3
  if unzip -Z1 "$zip" 2>/dev/null | grep -Fxq "$path"; then
    return 0
  fi
  failures+=("$msg — zip $zip does not contain entry: $path")
  return 1
}
assert_zip_missing() {
  local zip=$1 path=$2 msg=$3
  if unzip -Z1 "$zip" 2>/dev/null | grep -Fxq "$path"; then
    failures+=("$msg — zip $zip unexpectedly contains: $path")
    return 1
  fi
}

run_test() {
  local name=$1; shift
  local tmp; tmp=$(mktemp -d)
  local before_fail=${#failures[@]}

  ( "$@" "$tmp" )
  local rc=$?

  if [[ $rc -eq 0 && ${#failures[@]} -eq $before_fail ]]; then
    pass=$((pass + 1))
    printf '  ✅ %s\n' "$name"
  else
    fail=$((fail + 1))
    printf '  ❌ %s (rc=%d)\n' "$name" "$rc"
    while [[ ${#failures[@]} -gt $before_fail ]]; do
      local idx=$((${#failures[@]} - 1))
      printf '       %s\n' "${failures[$idx]}"
      unset 'failures[idx]'
    done
  fi

  rm -rf "$tmp"
}

# -----------------------------------------------------------------------------
# Test cases
# -----------------------------------------------------------------------------

test_zips_each_subfolder() {
  local tmp=$1
  mkdir -p "$tmp/foo" "$tmp/bar"
  touch "$tmp/foo/a.txt" "$tmp/bar/b.txt"
  bash "$SUT" --path="$tmp" >/dev/null
  assert_exists "$tmp/foo.zip" "foo.zip should be created" || return 1
  assert_exists "$tmp/bar.zip" "bar.zip should be created" || return 1
  assert_zip_contains "$tmp/foo.zip" "foo/a.txt" "foo.zip should contain a.txt" || return 1
  assert_zip_contains "$tmp/bar.zip" "bar/b.txt" "bar.zip should contain b.txt" || return 1
}

test_does_not_recurse_into_subfolders_of_subfolders() {
  # Script zips immediate subfolders. A nested folder shouldn't itself
  # produce a separate .zip at the root.
  local tmp=$1
  mkdir -p "$tmp/outer/inner"
  touch "$tmp/outer/inner/deep.txt"
  bash "$SUT" --path="$tmp" >/dev/null
  assert_exists  "$tmp/outer.zip"      "outer.zip should be created" || return 1
  assert_missing "$tmp/inner.zip"      "inner.zip should NOT be created at root" || return 1
  assert_zip_contains "$tmp/outer.zip" "outer/inner/deep.txt" "nested file should be inside outer.zip" || return 1
}

test_missing_path_errors() {
  local _tmp=$1
  if bash "$SUT" >/dev/null 2>&1; then
    failures+=("missing --path should have failed but exited 0")
    return 1
  fi
}

test_dry_run_creates_no_archives() {
  local tmp=$1
  mkdir -p "$tmp/foo"
  touch "$tmp/foo/a.txt"
  bash "$SUT" --path="$tmp" --dry-run >/dev/null
  assert_missing "$tmp/foo.zip" "dry-run must not create archive" || return 1
}

test_zip_FS_replaces_stale_entries() {
  # zip -FS (sync) should remove entries that no longer exist in the
  # source folder, rather than leaving the previous version inside the
  # archive (which plain `zip -r -9` would do).
  local tmp=$1
  mkdir -p "$tmp/foo"
  touch "$tmp/foo/old.txt"
  bash "$SUT" --path="$tmp" >/dev/null
  assert_zip_contains "$tmp/foo.zip" "foo/old.txt" "initial archive has old.txt" || return 1

  # Now remove old.txt, add new.txt, and re-run.
  rm "$tmp/foo/old.txt"
  touch "$tmp/foo/new.txt"
  bash "$SUT" --path="$tmp" >/dev/null
  assert_zip_contains "$tmp/foo.zip" "foo/new.txt"  "rerun should add new.txt" || return 1
  assert_zip_missing  "$tmp/foo.zip" "foo/old.txt"  "zip -FS should drop old.txt" || return 1
}

test_folder_with_spaces() {
  local tmp=$1
  mkdir -p "$tmp/my folder"
  touch "$tmp/my folder/file.txt"
  bash "$SUT" --path="$tmp" >/dev/null
  assert_exists "$tmp/my folder.zip" "folder-with-spaces should still zip" || return 1
  assert_zip_contains "$tmp/my folder.zip" "my folder/file.txt" "spaces preserved inside zip" || return 1
}

test_empty_parent_is_noop() {
  local tmp=$1
  bash "$SUT" --path="$tmp" >/dev/null
  # No subfolders → no archives; script should still exit 0.
}

# -----------------------------------------------------------------------------
# Runner
# -----------------------------------------------------------------------------

echo "Running compress-folders.sh tests…"

run_test "zips each immediate subfolder"          test_zips_each_subfolder
run_test "does not zip nested subfolders sep."    test_does_not_recurse_into_subfolders_of_subfolders
run_test "missing --path errors out"              test_missing_path_errors
run_test "dry-run creates no archives"            test_dry_run_creates_no_archives
run_test "zip -FS removes stale entries"          test_zip_FS_replaces_stale_entries
run_test "folder with spaces in name"             test_folder_with_spaces
run_test "empty parent is a no-op"                test_empty_parent_is_noop

echo
echo "─────────────────────────────"
printf '%d passed, %d failed\n' "$pass" "$fail"

[[ $fail -eq 0 ]]
