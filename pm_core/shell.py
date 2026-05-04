"""Helpers for safely constructing shell command strings.

Always use ``shell_quote`` on user-controlled values (PR titles, workdirs,
branch names, plan names, anything a user can write) before interpolating
into a shell pipeline. Raw f-string interpolation is unsafe — a single
apostrophe in a PR title is enough to break the surrounding quote and
turn the rest of the string into shell tokens.
"""

from __future__ import annotations

import shlex


def shell_quote(value: str) -> str:
    """Quote ``value`` for safe inclusion in a /bin/sh command string.

    Wrapper around :func:`shlex.quote`. Re-exported here so call sites have
    a single, intention-revealing import for shell-string construction.
    """
    return shlex.quote(value)
