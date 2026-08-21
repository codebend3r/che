#!/usr/bin/env bash
#
# Bootstrap che on a machine that has nothing yet.
#
#   ./install.sh                     from inside a clone
#   curl -fsSL https://raw.githubusercontent.com/codebend3r/che/main/install.sh | bash
#
# All it does is find (or make) the clone, find a python3 new enough to run the
# scripts, and hand over to bin/install.py, which does the real work. Every
# argument is passed straight through, so `./install.sh --yes --shells=zsh`
# works the same as `che install --yes --shells=zsh`.

set -euo pipefail

REPO_URL="${CHE_REPO_URL:-https://github.com/codebend3r/che.git}"
DEFAULT_DIR="${CHE_HOME:-$HOME/Developer/git/shell-functions}"
MIN_MAJOR=3
MIN_MINOR=12

red()   { printf '\033[1;31m%s\033[0m\n' "$*"; }
green() { printf '\033[0;32m%s\033[0m\n' "$*"; }
grey()  { printf '\033[90m%s\033[0m\n' "$*"; }

# Where is this script? Empty when piped in from curl, which is the signal to
# clone rather than to use a checkout that is not there.
script_dir() {
  local source="${BASH_SOURCE[0]:-}"
  [ -f "$source" ] || return 1
  cd -- "$(dirname -- "$source")" && pwd
}

find_python() {
  local candidate version
  for candidate in python3.14 python3.13 python3.12 python3 \
                   /opt/homebrew/bin/python3 /usr/local/bin/python3; do
    command -v "$candidate" >/dev/null 2>&1 || continue
    version=$("$candidate" -c 'import sys; print(sys.version_info[0] * 100 + sys.version_info[1])' 2>/dev/null) || continue
    if [ "$version" -ge $((MIN_MAJOR * 100 + MIN_MINOR)) ]; then
      command -v "$candidate"
      return 0
    fi
  done
  return 1
}

main() {
  local repo python

  if repo=$(script_dir) && [ -f "$repo/bin/che.py" ]; then
    grey "Using this clone: $repo"
  elif [ -f "$DEFAULT_DIR/bin/che.py" ]; then
    repo="$DEFAULT_DIR"
    grey "Using existing clone: $repo"
  else
    if ! command -v git >/dev/null 2>&1; then
      red "git is required to clone $REPO_URL"
      exit 1
    fi
    green "Cloning $REPO_URL -> $DEFAULT_DIR"
    mkdir -p "$(dirname -- "$DEFAULT_DIR")"
    git clone --quiet "$REPO_URL" "$DEFAULT_DIR"
    repo="$DEFAULT_DIR"
  fi

  if ! python=$(find_python); then
    red "No python3 ${MIN_MAJOR}.${MIN_MINOR}+ found."
    grey "Install one and run this again:"
    grey "  brew install python@3.13"
    exit 1
  fi
  grey "Using python: $python"

  # When this script is piped from curl, stdin is the script itself, so the
  # wizard could not read a single keystroke. Reconnect it to the terminal so
  # the interactive install still works; fall back to --yes when there is none.
  if [ ! -t 0 ]; then
    if (exec 3</dev/tty) 2>/dev/null; then
      exec 0</dev/tty
    else
      set -- --yes "$@"
    fi
  fi

  exec "$python" "$repo/bin/install.py" "$@"
}

main "$@"
