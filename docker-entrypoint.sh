#!/bin/bash
# Run install.sh --local --force from the mounted workspace so the pm
# editable install and entry-point symlink are set up before the session starts.
# Runs as root; install.sh is executed as the pm user.
if [ -f /workspace/install.sh ]; then
    cd /workspace && ./install.sh --local --force || true
fi

# Ensure /home/pm/.pm is pm-owned.  The hooks work (PR #166) added a
# bind-mount of ~/.pm/hooks into the container, and podman auto-creates
# the bind-mount parent (/home/pm/.pm) as root:root.  That leaves pm
# unable to create sibling directories (debug logs, session registry,
# etc.) and breaks plain ``pm`` invocations.  Repair ownership on every
# start so the bug can't re-materialise if the mount is re-created.
if [ -d /home/pm/.pm ]; then
    chown pm:pm /home/pm/.pm 2>/dev/null || true
fi

exec "$@"
