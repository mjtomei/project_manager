#!/usr/bin/env bash
# pm — Project Manager for Claude Code sessions

SOURCE="${BASH_SOURCE[0]}"
while [ -L "$SOURCE" ]; do
    DIR="$(cd "$(dirname "$SOURCE")" && pwd)"
    SOURCE="$(readlink "$SOURCE")"
    [[ "$SOURCE" != /* ]] && SOURCE="$DIR/$SOURCE"
done
SCRIPT_DIR="$(cd "$(dirname "$SOURCE")" && pwd)"
export PYTHONPATH="${SCRIPT_DIR}:${PYTHONPATH}"

if [ $# -eq 0 ]; then
    # No args: show help if no project found, otherwise launch TUI
    if python3 -m pm_core _check 2>/dev/null; then
        exec python3 -m pm_core tui
    else
        exec python3 -m pm_core help
    fi
elif [ "$1" = "help" ] || [ "$1" = "-h" ] || [ "$1" = "--help" ]; then
    exec python3 -m pm_core help
else
    exec python3 -m pm_core "$@"
fi
