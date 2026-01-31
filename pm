#!/usr/bin/env bash
# pm — Project Manager for Claude Code sessions
# Entrypoint script

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
export PYTHONPATH="${SCRIPT_DIR}:${PYTHONPATH}"

if [ $# -eq 0 ]; then
    exec python3 -m pm_core tui
else
    exec python3 -m pm_core "$@"
fi
