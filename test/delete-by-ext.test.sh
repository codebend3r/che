#!/usr/bin/env bash

# Tests for bin/files/delete-by-ext.sh
# Run: bash test/delete-by-ext.test.sh

set -uo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SUT="$SCRIPT_DIR/../bin/files/delete-by-ext.sh"

# The script defaults DRY_RUN=true (repo policy). Tests that actually expect
# deletion must run via this helper so the env override is explicit.
sut_real() { DRY_RUN=false bash "$SUT" "$@"; }

pass=0
fail=0
failures=()

assert_exists() {
  local f=$1 msg=$2
  if [[ -e "$f" ]]; then return 0; fi
  failures+=("$msg — expected to exist: $f")
  return 1
}

assert_missing() {
  local f=$1 msg=$2
  if [[ ! -e "$f" ]]; then return 0; fi
  failures+=("$msg — expected to be deleted: $f")
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

test_deletes_matching_extensions() {
  local tmp=$1
  touch "$tmp/a.jpg" "$tmp/b.png" "$tmp/c.mp4"
  sut_real --path="$tmp" --ext=jpg,png >/dev/null
  assert_missing "$tmp/a.jpg" "jpg should be deleted" || return 1
  assert_missing "$tmp/b.png" "png should be deleted" || return 1
  assert_exists  "$tmp/c.mp4" "mp4 should be preserved" || return 1
}

test_dry_run_deletes_nothing() {
  local tmp=$1
  touch "$tmp/a.jpg" "$tmp/b.png"
  bash "$SUT" --path="$tmp" --ext=jpg,png --dry-run >/dev/null
  assert_exists "$tmp/a.jpg" "dry-run must not delete jpg" || return 1
  assert_exists "$tmp/b.png" "dry-run must not delete png" || return 1
}

test_filename_with_spaces() {
  local tmp=$1
  mkdir -p "$tmp/sub dir"
  touch "$tmp/sub dir/with spaces.jpg" "$tmp/sub dir/keep.mp4"
  sut_real --path="$tmp" --ext=jpg >/dev/null
  assert_missing "$tmp/sub dir/with spaces.jpg" "spaces in path should still delete" || return 1
  assert_exists  "$tmp/sub dir/keep.mp4" "mp4 untouched" || return 1
}

test_filename_with_single_quote() {
  local tmp=$1
  touch "$tmp/weird'quote.jpg"
  sut_real --path="$tmp" --ext=jpg >/dev/null
  assert_missing "$tmp/weird'quote.jpg" "single-quote in filename should still delete" || return 1
}

test_filename_with_newline() {
  # Regression: the old `find | grep | tr '\n' '\0'` pipeline split a single
  # filename-with-newline into two paths and silently failed to delete it.
  local tmp=$1
  local weird
  weird="$(printf 'a\nb.jpg')"
  touch -- "$tmp/$weird"
  # Sanity: the OS actually created it
  assert_exists "$tmp/$weird" "setup: newline file must exist" || return 1
  sut_real --path="$tmp" --ext=jpg >/dev/null
  assert_missing "$tmp/$weird" "filename containing newline should still delete" || return 1
}

test_case_insensitive_extension() {
  local tmp=$1
  touch "$tmp/UPPER.JPG" "$tmp/MiXeD.PnG"
  sut_real --path="$tmp" --ext=jpg,png >/dev/null
  assert_missing "$tmp/UPPER.JPG"  "uppercase ext should match (-iname)" || return 1
  assert_missing "$tmp/MiXeD.PnG"  "mixed-case ext should match (-iname)" || return 1
}

test_recurses_into_subdirectories() {
  local tmp=$1
  mkdir -p "$tmp/a/b/c"
  touch "$tmp/a/b/c/deep.jpg" "$tmp/a/keep.mp4"
  sut_real --path="$tmp" --ext=jpg >/dev/null
  assert_missing "$tmp/a/b/c/deep.jpg" "deeply nested jpg should delete" || return 1
  assert_exists  "$tmp/a/keep.mp4"     "non-matching file preserved" || return 1
}

test_missing_path_errors() {
  local _tmp=$1
  # No --path provided — script should exit non-zero
  if bash "$SUT" --ext=jpg >/dev/null 2>&1; then
    failures+=("missing --path should have failed but exited 0")
    return 1
  fi
}

test_partial_extension_does_not_match() {
  # `mpg` extension should not match `.mpeg` files (regression check that
  # we anchor on full extension, not substring).
  local tmp=$1
  touch "$tmp/clip.mpeg" "$tmp/clip.mpg"
  sut_real --path="$tmp" --ext=mpg >/dev/null
  assert_exists  "$tmp/clip.mpeg" ".mpeg should NOT match --ext=mpg" || return 1
  assert_missing "$tmp/clip.mpg"  ".mpg should match --ext=mpg" || return 1
}

test_defaults_to_dry_run() {
  # Repo policy: without DRY_RUN=false or --dry-run=false, nothing is deleted.
  local tmp=$1
  touch "$tmp/a.jpg"
  bash "$SUT" --path="$tmp" --ext=jpg >/dev/null
  assert_exists "$tmp/a.jpg" "default invocation must NOT delete (dry-run default)" || return 1
}

# -----------------------------------------------------------------------------
# Runner
# -----------------------------------------------------------------------------

echo "Running delete-by-ext.sh tests…"

run_test "deletes matching extensions"          test_deletes_matching_extensions
run_test "dry-run deletes nothing"              test_dry_run_deletes_nothing
run_test "filename with spaces"                 test_filename_with_spaces
run_test "filename with single quote"           test_filename_with_single_quote
run_test "filename with newline (regression)"   test_filename_with_newline
run_test "case-insensitive extension matching"  test_case_insensitive_extension
run_test "recurses into subdirectories"         test_recurses_into_subdirectories
run_test "missing --path errors out"            test_missing_path_errors
run_test "partial extension does not match"     test_partial_extension_does_not_match
run_test "defaults to dry-run (policy)"         test_defaults_to_dry_run

echo
echo "─────────────────────────────"
printf '%d passed, %d failed\n' "$pass" "$fail"

[[ $fail -eq 0 ]]
