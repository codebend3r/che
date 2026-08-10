#!/usr/bin/env bash

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=bin/utils.sh
. "$SCRIPT_DIR/../utils.sh" --source-only

set -euo pipefail

# v2.0.0

usage() {
  cat <<EOF
Usage:
  $(basename "$0") [--owner=NAME[,NAME...]] [--author=NAME] [--pr-limit=N]
                   [--watch[=SECONDS]] [--interval=SECONDS]

Description:
  🎬 Show the latest GitHub Actions run for every open pull request you
     authored, across every repo you own — one row per PR, so a repo with
     five open PRs gets five rows. The repo name is a terminal hyperlink
     to that run.

     When a PR's head commit has several workflow runs, the row shows the
     one worth acting on: anything still in flight, else a failure, else
     the most recent run.

Options:
  --owner=NAME       Owner(s) to scan, comma-separated (default: your gh login)
  --author=NAME      PR author to match (default: your gh login)
  --pr-limit=N       Open PRs to inspect, max 100 (default: 100)
  --interval=SECONDS Refresh interval used by --watch (default: 15)
  --watch[=SECONDS]  Refresh every interval until interrupted
  --help             Show help
EOF
}

require_binary() {
  local bin=$1

  if ! command -v "$bin" >/dev/null 2>&1; then
    warning "❌ Missing required binary: $bin"
    exit 1
  fi
}

require_binary gh

OWNERS=""
AUTHOR=""
PR_LIMIT=100
INTERVAL=15
WATCH=false

# ⚙️  CLI — long flags only (see ../utils.sh).
while [[ $# -gt 0 ]]; do
  case "$1" in
    --owner=*)
      OWNERS="${1#*=}"
      shift
      ;;
    --author=*)
      AUTHOR="${1#*=}"
      shift
      ;;
    --pr-limit=*)
      PR_LIMIT="${1#*=}"
      shift
      ;;
    --interval=*)
      INTERVAL="${1#*=}"
      shift
      ;;
    --watch)
      WATCH=true
      shift
      ;;
    --watch=*)
      WATCH=true
      INTERVAL="${1#*=}"
      shift
      ;;
    --help|-h)
      usage
      exit 0
      ;;
    *)
      warning "❌ Unknown argument: $1"
      usage
      exit 1
      ;;
  esac
done

for pair in "pr-limit:$PR_LIMIT" "interval:$INTERVAL"; do
  name="${pair%%:*}"
  value="${pair#*:}"
  if ! [[ "$value" =~ ^[0-9]+$ ]]; then
    warning "❌ --${name} must be a non-negative integer (got: $value)"
    exit 1
  fi
done

# The GraphQL search connection caps out at 100 nodes per page.
[[ "$PR_LIMIT" -gt 100 ]] && PR_LIMIT=100
[[ "$PR_LIMIT" -lt 1 ]] && PR_LIMIT=1
[[ "$INTERVAL" -lt 1 ]] && INTERVAL=1

if ! gh auth status >/dev/null 2>&1; then
  warning "❌ Not logged in to GitHub. Run: gh auth login"
  exit 1
fi

GH_LOGIN=""
if [[ -z "$OWNERS" || -z "$AUTHOR" ]]; then
  GH_LOGIN="$(gh api user --jq .login)"
fi

[[ -z "$OWNERS" ]] && OWNERS="$GH_LOGIN"
[[ -z "$AUTHOR" ]] && AUTHOR="$GH_LOGIN"

# Materialize the escape sequences from utils.sh so awk/printf emit real color.
C_OFF="$(printf '%b' "$NC")"
C_RUNNING="$(printf '%b' "$CYAN")"
C_QUEUED="$(printf '%b' "$YELLOW")"
C_PASS="$(printf '%b' "$GREEN")"
C_FAIL="$(printf '%b' "$RED")"
C_HEAD="$(printf '%b' "$MAGENTA")"

status_color() {
  case "$1" in
    in_progress) printf '%s' "$C_RUNNING" ;;
    queued|waiting|pending|requested) printf '%s' "$C_QUEUED" ;;
    success) printf '%s' "$C_PASS" ;;
    failure|timed_out|startup_failure|action_required) printf '%s' "$C_FAIL" ;;
    *) printf '%s' "$C_OFF" ;;
  esac
}

status_icon() {
  case "$1" in
    in_progress) printf '🔄' ;;
    queued|waiting|pending|requested) printf '⏳' ;;
    success) printf '✅' ;;
    failure|timed_out|startup_failure) printf '❌' ;;
    cancelled) printf '🚫' ;;
    skipped) printf '⏩' ;;
    none) printf '➖' ;;
    *) printf '⚪' ;;
  esac
}

# Emoji occupy two terminal columns but count as one character, so `${#s}` pads
# workflow names like "🚦 CI" a column short. Add one per 4-byte UTF-8 sequence,
# plus one for each double-width emoji that still lives in the BMP (✅, ❌, …),
# which is only 3 bytes and so escapes the sequence count.
# Matched literally one glyph at a time: a bracket expression like [✅❌] matches
# by byte here, so it also eats unrelated 4-byte emoji.
WIDE_BMP=(✅ ❌ ⏳ ⏩ ⚪ ➖)

display_width() {
  local s=$1 wide glyph rest
  wide="$(printf '%s' "$s" | LC_ALL=C grep -o $'[\xF0-\xF4][\x80-\xBF]\{3\}' | grep -c '' || true)"

  for glyph in "${WIDE_BMP[@]}"; do
    rest="${s//"$glyph"/}"
    wide=$(( wide + ${#s} - ${#rest} ))
  done

  printf '%d' $(( ${#s} + wide ))
}

pad() {
  local value=$1 width=$2 gap
  gap=$(( width - $(display_width "$value") ))
  [[ $gap -lt 0 ]] && gap=0
  printf '%s%*s' "$value" "$gap" ''
}

# OSC 8 hyperlink. The escape sequences are zero-width, so the cell is padded
# from the plain text and only the text itself gets wrapped.
pad_link() {
  local url=$1 value=$2 width=$3 gap
  gap=$(( width - $(display_width "$value") ))
  [[ $gap -lt 0 ]] && gap=0

  if [[ -z "$url" ]]; then
    printf '%s%*s' "$value" "$gap" ''
    return
  fi

  printf '\033]8;;%s\033\\%s\033]8;;\033\\%*s' "$url" "$value" "$gap" ''
}

# ISO-8601 UTC -> epoch seconds. BSD date first, GNU as fallback.
iso_to_epoch() {
  date -j -u -f '%Y-%m-%dT%H:%M:%SZ' "$1" '+%s' 2>/dev/null \
    || date -u -d "$1" '+%s' 2>/dev/null \
    || true
}

# ISO-8601 UTC -> compact age ("45s", "12m", "3h", "2d").
iso_to_age() {
  local then now delta
  then="$(iso_to_epoch "$1")"

  if [[ -z "$then" ]]; then
    printf '-'
    return
  fi

  now="$(date -u '+%s')"
  delta=$((now - then))
  [[ $delta -lt 0 ]] && delta=0

  if [[ $delta -lt 60 ]]; then
    printf '%ds' "$delta"
  elif [[ $delta -lt 3600 ]]; then
    printf '%dm' $((delta / 60))
  elif [[ $delta -lt 86400 ]]; then
    printf '%dh' $((delta / 3600))
  else
    printf '%dd' $((delta / 86400))
  fi
}

# Seconds -> compact duration ("45s", "2m10s", "1h4m").
fmt_duration() {
  local secs=$1

  if [[ $secs -lt 60 ]]; then
    printf '%ds' "$secs"
  elif [[ $secs -lt 3600 ]]; then
    printf '%dm%02ds' $((secs / 60)) $((secs % 60))
  else
    printf '%dh%02dm' $((secs / 3600)) $(((secs % 3600) / 60))
  fi
}

# How long a run took. Completed runs are createdAt -> updatedAt; anything still
# in flight is measured against now, so the column ticks up while it runs.
run_duration() {
  local status=$1 created=$2 updated=$3 from to
  from="$(iso_to_epoch "$created")"

  if [[ -z "$from" ]]; then
    printf '-'
    return
  fi

  case "$status" in
    in_progress|queued|waiting|pending|requested) to="$(date -u '+%s')" ;;
    *) to="$(iso_to_epoch "$updated")" ;;
  esac

  if [[ -z "$to" ]]; then
    printf '-'
    return
  fi

  [[ $to -lt $from ]] && to=$from
  fmt_duration $((to - from))
}

read -r -d '' GRAPHQL_QUERY <<'GQL' || true
query($q: String!, $first: Int!) {
  search(query: $q, type: ISSUE, first: $first) {
    nodes {
      ... on PullRequest {
        number
        url
        headRefName
        repository { nameWithOwner }
        commits(last: 1) {
          nodes {
            commit {
              checkSuites(first: 20) {
                nodes {
                  status
                  conclusion
                  workflowRun {
                    url
                    createdAt
                    updatedAt
                    workflow { name }
                  }
                }
              }
            }
          }
        }
      }
    }
  }
}
GQL

# One row per PR. Among the head commit's workflow runs, prefer anything still
# in flight, then a failure, then the newest — the run actually worth looking at.
read -r -d '' JQ_ROWS <<'JQ' || true
.data.search.nodes[]
| select(.number != null)
| . as $pr
| [ $pr.commits.nodes[0].commit.checkSuites.nodes[]? | select(.workflowRun != null) ] as $suites
| ($suites | map(select(.status != "COMPLETED"))) as $live
| ($suites | map(select(.conclusion == "FAILURE" or .conclusion == "TIMED_OUT" or .conclusion == "STARTUP_FAILURE"))) as $bad
| (
    if ($live | length) > 0 then ($live | sort_by(.workflowRun.createdAt) | last)
    elif ($bad | length) > 0 then ($bad | sort_by(.workflowRun.createdAt) | last)
    elif ($suites | length) > 0 then ($suites | sort_by(.workflowRun.createdAt) | last)
    else null
    end
  ) as $s
| [
    $pr.repository.nameWithOwner,
    ($pr.number | tostring),
    $pr.headRefName,
    (if $s == null or $s.status == "COMPLETED" then "1" else "0" end),
    (
      if $s == null then "none"
      elif $s.status != "COMPLETED" then ($s.status | ascii_downcase)
      else (($s.conclusion // "unknown") | ascii_downcase)
      end
    ),
    (if $s == null then "-" else ($s.workflowRun.workflow.name // "-") end),
    (if $s == null then "" else $s.workflowRun.createdAt end),
    (if $s == null then "" else $s.workflowRun.updatedAt end),
    (if $s == null then $pr.url else $s.workflowRun.url end)
  ]
| @tsv
JQ

# `user:` qualifiers are OR'd by GitHub search, so several owners widen the sweep.
search_query() {
  local owner query="is:pr is:open archived:false author:${AUTHOR}"

  while IFS= read -r owner; do
    [[ -z "$owner" ]] && continue
    query+=" user:${owner}"
  done < <(printf '%s\n' "${OWNERS//,/$'\n'}")

  printf '%s' "$query"
}

# Every open PR and its head-commit check suites in a single GraphQL call, so a
# 15-second refresh stays well inside the rate limit.
fetch_rows() {
  gh api graphql \
    -f query="$GRAPHQL_QUERY" \
    -f q="$(search_query)" \
    -F first="$PR_LIMIT" \
    --jq "$JQ_ROWS" 2>/dev/null || true
}

render() {
  local rows repo_count pr_count single_owner

  single_owner=false
  [[ "$OWNERS" != *,* ]] && single_owner=true

  # In-flight rows first (live=0), then grouped by repo, newest run first.
  rows="$(fetch_rows | sort -t"$(printf '\t')" -k4,4 -k1,1 -k7,7r)"

  if [[ -z "$rows" ]]; then
    note "═══════════════════════════════════════════"
    note "🎬  all-actions — $(date '+%H:%M:%S')"
    note "═══════════════════════════════════════════"
    info "🫙 No open pull requests authored by ${AUTHOR} under: ${OWNERS}"
    return 0
  fi

  pr_count="$(printf '%s\n' "$rows" | grep -c '' | tr -d ' ')"
  repo_count="$(printf '%s\n' "$rows" | cut -f1 | sort -u | grep -c '' | tr -d ' ')"

  note "═══════════════════════════════════════════"
  note "🎬  all-actions — ${pr_count} open PR(s) · ${repo_count} repo(s) · $(date '+%H:%M:%S')"
  note "═══════════════════════════════════════════"

  local repo number branch live status workflow created updated url age took display cell
  local w_repo=4 w_pr=3 w_status=6 w_workflow=8 w_branch=6 w_age=4 w_took=5

  while IFS=$'\t' read -r repo number branch live status workflow created updated url; do
    [[ -z "$repo" ]] && continue
    display="$repo"
    [[ "$single_owner" == "true" ]] && display="${repo#*/}"
    cell="$(status_icon "$status") $status"
    [[ $(display_width "$display") -gt $w_repo ]] && w_repo=$(display_width "$display")
    [[ $(display_width "#$number") -gt $w_pr ]] && w_pr=$(display_width "#$number")
    [[ $(display_width "$cell") -gt $w_status ]] && w_status=$(display_width "$cell")
    [[ $(display_width "$workflow") -gt $w_workflow ]] && w_workflow=$(display_width "$workflow")
    [[ $(display_width "$branch") -gt $w_branch ]] && w_branch=$(display_width "$branch")
  done <<< "$rows"

  printf '%b%s  %s  %s  %s  %s  %s  %s%b\n' \
    "$C_HEAD" \
    "$(pad REPO "$w_repo")" \
    "$(pad PR "$w_pr")" \
    "$(pad STATUS "$w_status")" \
    "$(pad WORKFLOW "$w_workflow")" \
    "$(pad BRANCH "$w_branch")" \
    "$(pad AGE "$w_age")" \
    "TOOK" \
    "$C_OFF"

  local live_count=0 idle_count=0
  while IFS=$'\t' read -r repo number branch live status workflow created updated url; do
    [[ -z "$repo" ]] && continue
    display="$repo"
    [[ "$single_owner" == "true" ]] && display="${repo#*/}"
    age="$(iso_to_age "$created")"
    took="$(run_duration "$status" "$created" "$updated")"
    printf '%b%s  %s  %s  %s  %s  %s  %s%b\n' \
      "$(status_color "$status")" \
      "$(pad_link "$url" "$display" "$w_repo")" \
      "$(pad "#$number" "$w_pr")" \
      "$(pad "$(status_icon "$status") $status" "$w_status")" \
      "$(pad "$workflow" "$w_workflow")" \
      "$(pad "$branch" "$w_branch")" \
      "$(pad "$age" "$w_age")" \
      "$(pad "$took" "$w_took")" \
      "$C_OFF"
    if [[ "$live" == "0" ]]; then
      live_count=$((live_count + 1))
    else
      idle_count=$((idle_count + 1))
    fi
  done <<< "$rows"

  echo
  if [[ "$live_count" -eq 0 ]]; then
    success "😴 Nothing in flight — ${idle_count} open PR(s) showing their last run."
  else
    success "═══ ${live_count} in flight · ${idle_count} settled (last run) ═══"
  fi
}

if [[ "$WATCH" == "true" ]]; then
  # Ctrl-C during a watch loop is the normal exit, not a failure.
  trap 'echo; success "👋 Stopped watching."; exit 0' INT
  while true; do
    clear
    render || true
    info "🔁 Refreshing every ${INTERVAL}s — Ctrl-C to stop."
    sleep "$INTERVAL"
  done
fi

render
