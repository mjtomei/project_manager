#!/usr/bin/env bash
set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
VENV_DIR="$HOME/.local/share/pm/venv"
BIN_LINK="$HOME/.local/bin/pm"
# fake-claude is a standalone integration-test stand-in for real Claude,
# resolved by bare name from PATH (exactly like ``claude``) by the launcher, so
# it must be on PATH.  We install a tiny shim (not a symlink) that resolves the
# actual binary via ``pm which`` at run time — so the copy under test is used
# (the same resolution works inside containers, where pm may resolve to a
# /workspace checkout rather than the install dir).
FAKE_SHIM="$HOME/.local/bin/fake-claude"

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
    rm -f "$FAKE_SHIM"
    rm -rf "$VENV_DIR"
    echo "Removed $BIN_LINK, $FAKE_SHIM and $VENV_DIR"
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
    "$VENV_DIR/bin/pip" install -e "$SCRIPT_DIR[test]"

    mkdir -p "$HOME/.local/bin"
    ln -sf "$VENV_DIR/bin/pm" "$BIN_LINK"
    cat > "$FAKE_SHIM" << 'FAKEEOF'
#!/bin/sh
# pm: resolve fake-claude from the active pm install (pm which) so the copy
# under test is used (works inside containers too).
core="$(pm which 2>/dev/null | tail -n1)"
# A pipeline's status is tail's (almost always 0), so guard the value itself:
# an empty core makes dirname yield "." and exec a bogus relative path.
[ -n "$core" ] || exit 127
exec "$(dirname "$core")/bin/fake-claude" "$@"
FAKEEOF
    chmod 755 "$FAKE_SHIM"

    echo ""
    echo "Installed pm -> $BIN_LINK"
    echo "Installed fake-claude shim -> $FAKE_SHIM"
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
"$LOCAL_VENV/bin/pip" install -e "$SCRIPT_DIR[test]"

echo ""
echo "Installed pm into .venv/. To use it:"
echo "  source $LOCAL_VENV/bin/activate"
echo "  pm help"
echo ""
echo "To install globally to ~/.local/bin instead, run:"
echo "  ./install.sh --local"
