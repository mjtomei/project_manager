#!/usr/bin/env bash
set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
VENV_DIR="$HOME/.local/share/pm/venv"
BIN_LINK="$HOME/.local/bin/pm"

FORCE=false
MODE=""

usage() {
    echo "Usage: ./install.sh [--local | --uninstall] [--force]"
    echo ""
    echo "  (no flags)    Install into a local venv at .venv/"
    echo "  --local       Install into ~/.local/share/pm/venv and symlink to ~/.local/bin/pm"
    echo "  --uninstall   Remove the --local install"
    echo "  --force       Overwrite existing install"
}

for arg in "$@"; do
    case "$arg" in
        --force) FORCE=true ;;
        --local) MODE=local ;;
        --uninstall) MODE=uninstall ;;
        *) usage; exit 1 ;;
    esac
done

if [ "$MODE" = "uninstall" ]; then
    rm -f "$BIN_LINK"
    rm -rf "$VENV_DIR"
    echo "Removed $BIN_LINK and $VENV_DIR"
    exit 0
fi

if [ "$MODE" = "local" ]; then
    if [ -e "$BIN_LINK" ] && [ "$FORCE" = false ]; then
        # Check if it's our symlink or something else
        if [ -L "$BIN_LINK" ] && readlink "$BIN_LINK" | grep -q "$VENV_DIR"; then
            echo "Already installed (found $BIN_LINK -> $VENV_DIR)" >&2
            echo "Run with --force to reinstall." >&2
        else
            echo "$BIN_LINK already exists and may be a different tool:" >&2
            ls -l "$BIN_LINK" >&2
            echo "Remove it manually or run with --force to overwrite." >&2
        fi
        exit 1
    fi
    if [ -d "$VENV_DIR" ] && [ "$FORCE" = false ]; then
        echo "Already installed at $VENV_DIR" >&2
        echo "Run with --force to reinstall." >&2
        exit 1
    fi

    echo "Creating venv at $VENV_DIR ..."
    mkdir -p "$(dirname "$VENV_DIR")"
    python3 -m venv "$VENV_DIR"
    "$VENV_DIR/bin/pip" install -e "$SCRIPT_DIR"

    mkdir -p "$HOME/.local/bin"
    ln -sf "$VENV_DIR/bin/pm" "$BIN_LINK"

    echo ""
    echo "Installed pm -> $BIN_LINK"
    echo "Run 'pm help' to get started."
    exit 0
fi

LOCAL_VENV="$SCRIPT_DIR/.venv"
if [ -d "$LOCAL_VENV" ] && [ "$FORCE" = false ]; then
    echo "Already installed at $LOCAL_VENV" >&2
    echo "Run with --force to reinstall." >&2
    exit 1
fi

echo "Creating local venv at $LOCAL_VENV ..."
python3 -m venv "$LOCAL_VENV"
"$LOCAL_VENV/bin/pip" install -e "$SCRIPT_DIR"

echo ""
echo "Installed pm into .venv/. To use it:"
echo "  source $LOCAL_VENV/bin/activate"
echo "  pm help"
echo ""
echo "To install globally to ~/.local/bin instead, run:"
echo "  ./install.sh --local"
