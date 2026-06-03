#!/usr/bin/env bash

# Tests for bin/files/delete-empty-folders.sh
# Run: bash test/delete-empty-folders.test.sh

set -uo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SUT="$SCRIPT_DIR/../bin/files/delete-empty-folders.sh"

sut_real() { DRY_RUN=false bash "$SUT" "$@"; }

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
  failures+=("$2 — expected to be deleted: $1")
  return 1
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

test_deletes_truly_empty_folder() {
  local tmp=$1
  mkdir -p "$tmp/empty"
  sut_real --path="$tmp" >/dev/null
  assert_missing "$tmp/empty" "truly-empty folder should be deleted" || return 1
}

test_preserves_folder_with_visible_files() {
  local tmp=$1
  mkdir -p "$tmp/has-stuff"
  touch "$tmp/has-stuff/file.txt"
  sut_real --path="$tmp" >/dev/null
  assert_exists "$tmp/has-stuff" "folder with visible file should be preserved" || return 1
  assert_exists "$tmp/has-stuff/file.txt" "contents untouched" || return 1
}

test_preserves_folder_with_only_hidden_files() {
  # Regression: previous version called rm -rf on folders containing only
  # hidden files (.DS_Store, ._*, .git*), silently wiping them.
  local tmp=$1
  mkdir -p "$tmp/hidden-only"
  touch "$tmp/hidden-only/.DS_Store"
  mkdir -p "$tmp/dotgit-only/.git"
  touch "$tmp/dotgit-only/.git/HEAD"
  sut_real --path="$tmp" >/dev/null
  assert_exists "$tmp/hidden-only"             "hidden-only folder must be preserved" || return 1
  assert_exists "$tmp/hidden-only/.DS_Store"   ".DS_Store must NOT be silently wiped" || return 1
  assert_exists "$tmp/dotgit-only"             ".git-containing folder must be preserved" || return 1
  assert_exists "$tmp/dotgit-only/.git/HEAD"   ".git/HEAD must not be wiped" || return 1
}

test_cascades_nested_empties() {
  local tmp=$1
  mkdir -p "$tmp/a/b/c"
  sut_real --path="$tmp" >/dev/null
  assert_missing "$tmp/a/b/c" "innermost empty should be deleted" || return 1
  assert_missing "$tmp/a/b"   "mid-level empty should cascade" || return 1
  assert_missing "$tmp/a"     "outermost empty should cascade" || return 1
}

test_partial_cascade_stops_at_non_empty() {
  local tmp=$1
  mkdir -p "$tmp/keep/empty"
  touch "$tmp/keep/marker.txt"
  sut_real --path="$tmp" >/dev/null
  assert_missing "$tmp/keep/empty"      "leaf empty should be deleted" || return 1
  assert_exists  "$tmp/keep"            "parent with file must stay" || return 1
  assert_exists  "$tmp/keep/marker.txt" "marker file untouched" || return 1
}

test_does_not_delete_root() {
  local tmp=$1
  # tmp itself is empty after mktemp -d; script must not delete the path
  # the user passed in via --path.
  sut_real --path="$tmp" >/dev/null
  assert_exists "$tmp" "root --path must never be deleted" || return 1
}

test_dry_run_deletes_nothing() {
  local tmp=$1
  mkdir -p "$tmp/empty"
  bash "$SUT" --path="$tmp" --dry-run >/dev/null
  assert_exists "$tmp/empty" "dry-run must not delete" || return 1
}

test_defaults_to_dry_run() {
  local tmp=$1
  mkdir -p "$tmp/empty"
  bash "$SUT" --path="$tmp" >/dev/null
  assert_exists "$tmp/empty" "default invocation must NOT delete (dry-run default)" || return 1
}

test_missing_path_errors() {
  local _tmp=$1
  if bash "$SUT" >/dev/null 2>&1; then
    failures+=("missing --path should have failed but exited 0")
    return 1
  fi
}

test_folder_with_spaces() {
  local tmp=$1
  mkdir -p "$tmp/some empty folder"
  sut_real --path="$tmp" >/dev/null
  assert_missing "$tmp/some empty folder" "spaces in folder name should still delete" || return 1
}

# -----------------------------------------------------------------------------
# Runner
# -----------------------------------------------------------------------------

echo "Running delete-empty-folders.sh tests…"

run_test "deletes truly-empty folder"               test_deletes_truly_empty_folder
run_test "preserves folder with visible files"      test_preserves_folder_with_visible_files
run_test "preserves hidden-only folder (regr)"      test_preserves_folder_with_only_hidden_files
run_test "cascades nested empty chain"              test_cascades_nested_empties
run_test "partial cascade stops at non-empty"       test_partial_cascade_stops_at_non_empty
run_test "does not delete --path root"              test_does_not_delete_root
run_test "dry-run deletes nothing"                  test_dry_run_deletes_nothing
run_test "defaults to dry-run (policy)"             test_defaults_to_dry_run
run_test "missing --path errors out"                test_missing_path_errors
run_test "folder with spaces in name"               test_folder_with_spaces

echo
echo "─────────────────────────────"
printf '%d passed, %d failed\n' "$pass" "$fail"

[[ $fail -eq 0 ]]
