#!/bin/bash
# Run install.sh --local --force from the mounted workspace so the pm
# editable install and entry-point symlink are set up before the session starts.
# Runs as root; install.sh is executed as the pm user.
if [ -f /workspace/install.sh ]; then
    cd /workspace && ./install.sh --local --force || true
fi
exec "$@"
