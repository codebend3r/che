#!/opt/homebrew/bin/bash

# -----------------------------------------------------------------------------
# Delete duplicate MKV/MP4 files under a root directory.
#
# High-level pipeline (each phase is spelled out inline below too):
#
#   1) Parse CLI flags and normalize booleans/strategy (+ optional env overrides).
#   2) Resolve --path to an absolute directory and sanity-check permissions.
#   3) If strategy needs hashes, prove we have a SHA-256 tool before scanning.
#   4) find(1) every .mkv/.mp4 recursively; skip AppleDouble "._*" sidecars.
#   5) For each file, compute a "duplicate group key" (depends on --strategy).
#      Write TAB-separated rows: "<group_key>TAB<absolute_path>" to a temp file.
#      Keys use ASCII RS ($'\036') internally to concat fields safely.
#   6) sort(1) rows by group_key so identical keys are contiguous.
#   7) Walk sorted rows: accumulate paths until the group key changes, then send
#      the accumulated list to process_group().
#   8) process_group picks one keeper (largest file; tie-break lexically by path)
#      and deletes or dry-run-reports every other member of that group.
#   9) EXIT trap deletes the tempfile; print totals.
#
# v2.2.1
# -----------------------------------------------------------------------------

# Resolve this script's folder so utils.sh loads even when cwd is unrelated.
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# Pull in shared color printers + format_bytes() for human-readable sizes.
# shellcheck source=bin/utils.sh
. "$SCRIPT_DIR/../utils.sh" --source-only

# errexit / nounset / fail-on-pipeline — catch typos & silent pipe failures early.
set -euo pipefail

# Announce cwd for logs (helps when diagnosing "wrong tree" surprises).
info "Running command in $(pwd)"

# Prints --help body; intentionally user-facing prose, not code comments.
usage() {
  cat <<EOF
Usage:
  $(basename "$0") --path=/path/to/media [--strategy=MODE] [--dry-run] [--verbose]

Description:
  Group video files (.mkv/.mp4) under --path using a duplicate rule, keep one member
  of each duplicate group (largest file wins; ties break by path — deterministic),
  delete the others when not in dry-run.

Strategies (--strategy):

  episode   Same directory + identical SxxEyy token (tv-style names). Ignores files
             without such a token — original behavior.

  filename  Same directory + identical basename — exact filename duplicates only.

  size      Same directory + identical byte size. Fast but CAN mis-group different
             videos that coincidentally match size.

  hash      Globally grouped by SHA-256 checksum (byte-identical copies anywhere
             under root). Reads every file fully — slow on huge trees.

  all       Requires same-directory basename to match byte size AND SHA-256 digest.
             Reads every scanned file fully. Strong confirmation before delete.

Defaults:
  --strategy=episode

Security:
  Defaults to dry-run when you invoke the script by path (safe for scripting).
  Typical setup sources delete-duplicate-videos from .zshrc with DRY_RUN=false so interactive
  use matches the historic single-command behavior; use delete-duplicate-videos-dr to preview deletes only.

Options:
  --path=PATH     Required directory to scan
  --strategy=MODE episode | filename | size | hash | all
  --dry-run       Show removals only — no deletes (same as env DRY_RUN=true)
  --dry-run=BOOL  Explicit true|false (aliases: yes|no, 1|0)
  --verbose       Extra per-file logging
  --verbose=BOOL  Explicit true|false
  --help, -h      This help

Env:
  STRATEGY=MODE        Same spelling as --strategy (default episode)
  DRY_RUN=true|false   Overrides default dry-run when set (wrapper uses this)

Examples:
  $(basename "$0") --path=./Shows --strategy=filename
  DRY_RUN=false $(basename "$0") --path=./Shows --strategy=hash

  If you symlink this repo's .zshrc helpers: delete-duplicate-videos passes DRY_RUN=false;
  delete-duplicate-videos-dr forces preview-only.
EOF
}

# ---------------------------------------------------------------------------
# Globals & regexes
# ---------------------------------------------------------------------------

# RECORD SEPARATOR: glue multiple logical fields inside one sort key without using
# TAB/newline/colon tricks. Extremely unlikely to appear in real directory names.
KEY_RS=$'\036'

# Pick out a TV-ish token like S03E07 / s03e12 from a filename (basename only).
EP_REGEX='[Ss][0-9]{2}[Ee][0-9]{2,3}'

# Default booleans/strategy BEFORE argv parsing allows env overrides, then CLI wins.
DRY_RUN="${DRY_RUN:-true}"                   # Repo policy: destructive tools default preview-only unless wrapper sets env.
VERBOSE=false                                # Loud per-file diagnostics off unless --verbose / env later.
STRATEGY="${STRATEGY:-episode}"             # Canonical duplicate definition for this repo historically.
ROOT_DIR=""                                  # Filled by --path=… then cd-pwd-absolutised.
DELETED_COUNT=0                              # How many deletes we attempted (or simulated in dry-run).
SCANNED_COUNT=0                              # How many find hits we touched (every mkv/mp4 candidate).
DUPLICATE_GROUPS=0                           # How many multi-file groups yielded at least one deletion candidate.
RECLAIM_BYTES=0                              # Running sum of byte sizes we would reclaim / deleted.

# Map human-ish truthy strings to literal "true" / "false" for predictable tests.
normalize_bool() {
  local v
  v=$(printf '%s' "${1:-}" | tr '[:upper:]' '[:lower:]')
  case "$v" in
    true | yes | 1 | on)  echo true ;;
    false | no | 0 | off) echo false ;;
    *)                      echo ""; return 1 ;;   # Signals caller that input was neither truthy nor falsey.
  esac
}

# Thin wrapper around normalize_bool(): truth test usable in conditionals (`if`).
is_true() {
  [[ "$(normalize_bool "$1")" == true ]] 2>/dev/null
}

# Hard dependency guard — fail fast instead of midway through rm/sort/find.
require_binary() {
  local bin=$1

  if ! command -v "$bin" >/dev/null 2>&1; then
    warning "Missing required binary: $bin"
    exit 1
  fi
}

# Core unix tools everywhere this script expects to run.
require_binary find
require_binary sort
require_binary rm
require_binary bc     # Needed indirectly by utils.sh:format_bytes arithmetic.
require_binary awk    # Used to pick hex tokens out of openssl/sha256sum/shasum output lines.

# Collapse synonyms (tv ≈ episode, name ≈ filename, digest ≈ hash, …).
normalize_strategy() {
  local v
  v=$(printf '%s' "${1:-}" | tr '[:upper:]' '[:lower:]')
  case "$v" in
    episode | tv)                echo episode ;;
    filename | file | basename | name) echo filename ;;
    size | bytes )                echo size ;;
    hash | checksum | sha256 | digest) echo hash ;;
    all | combined )              echo all ;;
    *)
      echo ""
      return 1
      ;;
  esac
}

# Canonicalize openssl/sha256sum/shasum output to a lowercase 64-char hex string.
_sha256_normalize_print() {
  local hex=$1 lc
  lc=$(printf '%s' "$hex" | tr '[:upper:]' '[:lower:]')
  lc=${lc//$'\t'/}
  lc=${lc//$'\n'/}
  lc=${lc// /}
  [[ ${#lc} -eq 64 ]] || return 1
  printf '%s' "$lc"
}

# Computes SHA-256 digest of FILE; tries multiple backends because mac/Linux differ.
sha256_hex_file() {
  local f=$1 hex=""
  # 1) OpenSSL is almost always installed on desktop macOS/Linux with dev tools.
  if command -v openssl >/dev/null 2>&1; then
    # Last field on the openssl line is the hex digest regardless of parentheses formatting.
    hex=$(openssl dgst -sha256 "$f" 2>/dev/null | awk '{print $NF}')
    if hex=$(_sha256_normalize_print "$hex"); then
      printf '%s' "$hex"
      return 0
    fi
  fi
  # 2) GNU coreutils path (common on Linux/Homebrew gnu).
  if command -v sha256sum >/dev/null 2>&1; then
    hex=$(sha256sum "$f" 2>/dev/null | awk '{print $1}')
    if hex=$(_sha256_normalize_print "$hex"); then
      printf '%s' "$hex"
      return 0
    fi
  fi
  # 3) macOS perl Digest wrapper (Perl ships with Xcode CLT installs).
  if command -v shasum >/dev/null 2>&1; then
    hex=$(shasum -a 256 "$f" 2>/dev/null | awk '{print $1}')
    if hex=$(_sha256_normalize_print "$hex"); then
      printf '%s' "$hex"
      return 0
    fi
  fi
  return 1
}

# Proactive smoke-test: hashing huge trees is pointless if digest tools are broken/
# sandbox-blocked — fail cheaply against an empty temp file digest.
ensure_hash_backend() {
  local tmp=""
  tmp=$(mktemp)
  [[ -z "$tmp" ]] && tmp=$(mktemp -t dvhash)
  # Truncate-safe empty file digest must succeed for any sane backend.
  : >"$tmp" || true
  if ! sha256_hex_file "$tmp" >/dev/null; then
    rm -f "$tmp"
    warning "SHA-256 hashing requires openssl, sha256sum, or shasum -a 256 (none usable)."
    exit 1
  fi
  rm -f "$tmp"
}

# Cross-platform byte size: BSD stat (-f %z mac) OR GNU stat (-c%s linux).
file_bytes() {
  local f=$1 sz
  if sz=$(stat -f %z "$f" 2>/dev/null); then
    printf '%s\n' "${sz}"
  elif sz=$(stat -c%s "$f" 2>/dev/null); then
    printf '%s\n' "${sz}"
  else
    return 1
  fi
}

# Emit one SORT row for FILE under STRATEGY, or silently skip irrelevant files (code 2).
emit_row_for_file() {
  local file=$1 strat=$2 dir name size digest key

  dir=$(dirname "$file")
  name=$(basename "$file")
  # Defence-in-depth beside find-prune rules: skip AppleDouble sidecars outright.
  [[ "$name" == ._* ]] && return 2

  case "$strat" in
    episode)
      # Only TV-shaped names participate; unrelated adult/movie filenames are ignored (return 2 = skip quietly).
      [[ $name =~ $EP_REGEX ]] || return 2
      # Group duplicates that share BOTH folder identity AND the captured SxxExx token string.
      key="${dir}${KEY_RS}${BASH_REMATCH[0]}"
      ;;
    filename)
      # Exact basename collisions confined to same parent directory only.
      key="${dir}${KEY_RS}${name}"
      ;;
    size)
      # Collisions are "same folder + identical byte-length" — may false-positive unrelated media.
      if ! size="$(file_bytes "$file")"; then
        warning "SKIP: unreadable size: $file"
        return 2
      fi
      key="${dir}${KEY_RS}${size}"
      ;;
    hash)
      is_true "$VERBOSE" && note "HASH: $file"
      # Entire subtree dedup irrespective of dirs — digest alone is grouping key.
      if ! digest="$(sha256_hex_file "$file")"; then
        warning "SKIP: could not hash: $file"
        return 2
      fi
      key="${digest}"
      ;;
    all)
      # Conservative composite: basename + numeric size proof + cryptographic digest, all anchored to dirname.
      if ! size="$(file_bytes "$file")"; then
        warning "SKIP: unreadable size: $file"
        return 2
      fi
      is_true "$VERBOSE" && note "HASH: $file"
      if ! digest="$(sha256_hex_file "$file")"; then
        warning "SKIP: could not hash: $file"
        return 2
      fi
      key="${dir}${KEY_RS}${name}${KEY_RS}${size}${KEY_RS}${digest}"
      ;;
    *)
      warning "Internal error: unknown strategy '$strat'"
      exit 1
      ;;
  esac

  # One row per surviving file — column1 is opaque group key for sort(1); column2 is absolute path string.
  printf '%s\t%s\n' "$key" "$file"
  return 0
}

# ---------------------------------------------------------------------------
# ⚙️  Argument parsing — `--flag` / `--flag=value` (see ../utils.sh)
# ---------------------------------------------------------------------------

while [[ $# -gt 0 ]]; do
  case "$1" in
    --path=*)
      ROOT_DIR="${1#*=}"
      shift
      ;;
    --strategy=*)
      if ! s=$(normalize_strategy "${1#*=}"); then
        warning "Invalid --strategy value: ${1#*=}"
        usage
        exit 1
      fi
      STRATEGY="$s"
      shift
      ;;
    --dry-run=*)
      d=$(normalize_bool "${1#*=}") || {
        warning "Invalid --dry-run value: ${1#*=}"
        usage
        exit 1
      }
      DRY_RUN="$d"
      shift
      ;;
    --dry-run)
      DRY_RUN=true
      shift
      ;;
    --verbose=*)
      v=$(normalize_bool "${1#*=}") || {
        warning "Invalid --verbose value: ${1#*=}"
        usage
        exit 1
      }
      [[ "$v" == true ]] && VERBOSE=true || VERBOSE=false
      shift
      ;;
    --verbose)
      VERBOSE=true
      shift
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    *)
      warning "Unknown argument: $1"
      usage
      exit 1
      ;;
  esac
done

# Normalize env-inherited knobs again so STRATEGY=HASH / DRY_RUN=YES style exports work uniformly.
if ! tmp=$(normalize_bool "$DRY_RUN"); then
  warning "Invalid DRY_RUN env / state: '$DRY_RUN'"
  usage
  exit 1
fi
DRY_RUN="$tmp"

if ! tmp=$(normalize_bool "$VERBOSE"); then
  warning "Invalid VERBOSE flag state: '$VERBOSE'"
  usage
  exit 1
fi
VERBOSE="$tmp"

if ! STRATEGY="$(normalize_strategy "${STRATEGY:-episode}")"; then
  warning "Invalid STRATEGY (env/--strategy): '${STRATEGY:-}'"
  usage
  exit 1
fi

note "Scanning: ${ROOT_DIR}"
note "Strategy: ${STRATEGY}"
note "Dry run: ${DRY_RUN}"
note "Verbose: ${VERBOSE}"
note "----------------------------------------------------"

[[ -z "$ROOT_DIR" ]] && { warning "Missing required argument: --path"; exit 1; }

# Realpath-lite: rejects missing paths and strips ../ components so sort keys dirname matches find output reliably.
if ! ROOT_DIR="$(cd "$ROOT_DIR" && pwd)"; then
  warning "Could not resolve directory: '${ROOT_DIR}'."
  exit 1
fi

[[ ! -d "$ROOT_DIR" ]] && { warning "The provided path '$ROOT_DIR' is not a valid directory."; exit 1; }

# Hash strategies dominate runtime — verify tooling before hashing thousands of gigs.
if [[ "$STRATEGY" == hash || "$STRATEGY" == all ]]; then
  ensure_hash_backend
fi

# Forewarn risky strategies so logs double as lightweight operator education.
case "$STRATEGY" in
  size)
    info "NOTICE: grouping by SIZE can flag unrelated videos with identical byte lengths."
    ;;
  hash | all)
    info "NOTICE: hashing reads every scanned file entirely — slow on huge libraries."
    ;;
esac

is_true "$DRY_RUN" && info "Running in dry-run mode — no files will be deleted."
is_true "$VERBOSE" && info "Verbose mode — per-file tracing enabled."

# Temporary aggregation file — survives until EXIT trap clears it (even abrupt failures).
TMPFILE=$(mktemp)
trap '[[ -n "$TMPFILE" && -f "$TMPFILE" ]] && rm -f "$TMPFILE"' EXIT

# ---------------------------------------------------------------------------
# Phase A — Enumerate inputs & materialize grouping rows
# ---------------------------------------------------------------------------

while IFS= read -r -d '' file; do
  ((SCANNED_COUNT++))                                                   # Raw counter of every *.mkv|*.mp4 seen.
  is_true "$VERBOSE" && info "SCANNING: $file"
  # Redirect-append each emitted row OR ignore emit_row_for_file's skip statuses (codes !=0) without aborting errexit loops.
  emit_row_for_file "$file" "$STRATEGY" >>"$TMPFILE" || true
done < <(
  # find's -print0 / read's -d '' pair handles spaces/special chars in paths safely.
  find "$ROOT_DIR" \( -iname '*.mkv' -o -iname '*.mp4' \) \
    -type f -not -name '._*' -print0
)

# Stable lexicographic sort pulls identical duplicate keys consecutive for linear aggregation pass below.
LC_ALL=C sort -t $'\t' -k1,1 "$TMPFILE" -o "$TMPFILE"

# ---------------------------------------------------------------------------
# Phase B — For one duplicate cohort, compute keeper vs deletees
# ---------------------------------------------------------------------------

process_group() {
  local files=("$@")
  local count=${#files[@]}

  # Singleton — nothing to prune.
  [[ $count -le 1 ]] && return

  # Build TAB records "sizeTABpath" suitable for numeric sort descending on size bytes.
  local size_file_list=()
  local f size

  local tab=$'\t'
  for f in "${files[@]}"; do
    [[ -f "$f" ]] || continue                                                  # symlink-to-missing guarded.
    if ! size="$(file_bytes "$f")"; then
      warning "SKIP: unreadable size: $f"
      continue
    fi
    size_file_list+=("${size}${tab}${f}")                                     # Tie-break handled by PATH sort tie column.
  done

  # After stat failures possibly removed candidates — maybe only one survives.
  [[ ${#size_file_list[@]} -le 1 ]] && return

  # Hydrate Bash array sorted_lines WITHOUT mapfile so macOS Bash 3.2 source compatibility holds.
  local sorted_lines=()
  local _ln
  while IFS= read -r _ln; do
    sorted_lines+=("$_ln")
  done < <(
    printf '%s\n' "${size_file_list[@]}" | LC_ALL=C sort -t "$tab" -k1,1nr -k2,2  # Largest size first; same-size tie alphabetical path.
  )

  (( ${#sorted_lines[@]} > 1 )) && ((DUPLICATE_GROUPS++))                  # Histogram of groups that demanded action.

  if [[ ${#sorted_lines[@]} -gt 0 ]]; then
    local line="${sorted_lines[0]}" size_keep file_keep
    size_keep="${line%%"$tab"*}"                                              # Peel leading numeric chunk.
    file_keep="${line#*"$tab"}"
    is_true "$VERBOSE" && info "KEEPING: $file_keep ($(format_bytes "$size_keep"))"
  fi

  # Everything after index 0 is duplicate material — delete preview or unlink for real depending on dry-run toggle.
  local i line size_del file_del size_human
  for (( i = 1; i < ${#sorted_lines[@]}; i++ )); do
    line="${sorted_lines[$i]}"
    size_del="${line%%"$tab"*}"
    file_del="${line#*"$tab"}"
    size_human=$(format_bytes "$size_del")

    if is_true "$DRY_RUN"; then
      ((DELETED_COUNT++))
      RECLAIM_BYTES=$((RECLAIM_BYTES + size_del))
      warning "[DRY-RUN] ❌ Would delete: $file_del ($size_human)"
      continue
    fi

    warning "❌ Deleting: $file_del ($size_human)"
    if rm -f -- "$file_del"; then
      ((DELETED_COUNT++))
      RECLAIM_BYTES=$((RECLAIM_BYTES + size_del))
    fi
  done
}

# ---------------------------------------------------------------------------
# Phase C — Stitch sorted rows back into contiguous groups keyed by dup_key column
# ---------------------------------------------------------------------------

current_key=""
matches=()

while IFS=$'\t' read -r dup_key filepath || [[ -n "${filepath:-}${dup_key:-}" ]]; do
  # Skip malformed blanks (should never happen unless temp file corrupted).
  [[ -z "${dup_key:-}" || -z "${filepath:-}" ]] && continue

  if [[ "$dup_key" != "$current_key" && ${#matches[@]} -gt 0 ]]; then
    # Key boundary detected — finalize previous accumulator before starting new group bucket.
    process_group "${matches[@]}"
    matches=()
  fi

  current_key="$dup_key"
  matches+=("$filepath")
done < "$TMPFILE"

# Flush trailing group — read loop exited before emitting synthetic boundary token.
if [[ ${#matches[@]} -gt 0 ]]; then
  process_group "${matches[@]}"
fi

if is_true "$DRY_RUN"; then
  log "Total files that would be deleted: $DELETED_COUNT"
else
  log "Total files deleted: $DELETED_COUNT"
fi

log "Duplicate groups merged ($STRATEGY): $DUPLICATE_GROUPS (~$(format_bytes "$RECLAIM_BYTES") freed)"

log "Total files scanned: $SCANNED_COUNT"
log "Scanning complete."
