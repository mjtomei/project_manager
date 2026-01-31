#!/usr/bin/env bash
set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BIN_DIR="$HOME/.local/bin"

mkdir -p "$BIN_DIR"
ln -sf "$SCRIPT_DIR/pm" "$BIN_DIR/pm"

echo "Installed pm -> $BIN_DIR/pm"

# Check dependencies
missing=""
python3 -c "import click" 2>/dev/null || missing="$missing click"
python3 -c "import yaml" 2>/dev/null || missing="$missing pyyaml"
python3 -c "import textual" 2>/dev/null || missing="$missing textual"

if [ -n "$missing" ]; then
    echo ""
    echo "Missing Python packages:$missing"
    echo "Install them with:"
    echo "  pip install$missing"
fi

# Check PATH
if ! echo "$PATH" | tr ':' '\n' | grep -q "^$BIN_DIR$"; then
    echo ""
    echo "$BIN_DIR is not on your PATH. Add this to your shell rc:"
    echo "  export PATH=\"\$HOME/.local/bin:\$PATH\""
fi

echo ""
echo "Run 'pm help' to get started."
