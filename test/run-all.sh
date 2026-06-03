#!/usr/bin/env bash

# Run every test/*.test.sh suite and summarize pass/fail counts.
# Usage: bash test/run-all.sh

set -uo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

shopt -s nullglob
suites=("$SCRIPT_DIR"/*.test.sh)
shopt -u nullglob

if [[ ${#suites[@]} -eq 0 ]]; then
  echo "No test suites found in $SCRIPT_DIR"
  exit 0
fi

passed_suites=0
failed_suites=0
failed_names=()

for suite in "${suites[@]}"; do
  name="$(basename "$suite")"
  echo "▶ $name"
  if bash "$suite"; then
    passed_suites=$((passed_suites + 1))
  else
    failed_suites=$((failed_suites + 1))
    failed_names+=("$name")
  fi
  echo
done

echo "═════════════════════════════"
printf 'Suites: %d passed, %d failed (of %d)\n' \
  "$passed_suites" "$failed_suites" "${#suites[@]}"

if [[ $failed_suites -gt 0 ]]; then
  echo "Failed:"
  for n in "${failed_names[@]}"; do
    echo "  • $n"
  done
  exit 1
fi
