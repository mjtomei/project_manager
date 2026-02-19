"""Entry point wrapper that prefers local pm_core when available.

When running from a directory containing pm_core (e.g., a workdir clone),
this wrapper uses the local version instead of the installed one. This
enables testing changes in PR workdirs without reinstalling.

The wrapper also checks ~/.pm/sessions/ for session overrides, allowing
pm meta sessions to redirect the installation to their working directory.
"""
import hashlib
import os
import sys
from pathlib import Path


def _get_session_tag() -> str | None:
    """Generate session tag from current git repository."""
    from pm_core.git_ops import get_git_root, get_github_repo_name

    git_root = get_git_root()
    if not git_root:
        return None

    repo_name = get_github_repo_name(git_root) or git_root.name
    path_hash = hashlib.md5(str(git_root).encode()).hexdigest()[:8]

    return f"{repo_name}-{path_hash}"


def _find_active_override() -> str | None:
    """Check for an active session override.

    Derives session tag from current git repo and checks for override file.
    """
    session_tag = _get_session_tag()
    if not session_tag:
        return None

    override_file = Path.home() / ".pm" / "sessions" / session_tag / "override"
    if not override_file.exists():
        return None

    try:
        content = override_file.read_text().strip()
        if content:
            p = Path(content)
            if p.exists() and (p / "pm_core").is_dir():
                return str(p)
    except (OSError, IOError):
        pass
    return None


def find_local_pm_core():
    """Find pm_core in cwd or parent directories."""
    cwd = os.getcwd()
    # Check cwd and up to 3 parent directories
    for _ in range(4):
        candidate = os.path.join(cwd, "pm_core")
        if os.path.isdir(candidate) and os.path.isdir(os.path.join(candidate, "cli")):
            return cwd
        parent = os.path.dirname(cwd)
        if parent == cwd:
            break
        cwd = parent
    return None


def main():
    """Entry point that prefers local pm_core.

    Priority order:
    1. Active session override (from ~/.pm/sessions/{tag}/override)
    2. Local pm_core in cwd or parent directories
    3. Installed pm_core
    """
    # First check for active session override
    override_root = _find_active_override()
    if override_root and override_root not in sys.path:
        sys.path.insert(0, override_root)
        to_remove = [k for k in sys.modules if k == 'pm_core' or k.startswith('pm_core.')]
        for k in to_remove:
            del sys.modules[k]
    else:
        # Check for local pm_core before importing cli
        local_root = find_local_pm_core()
        if local_root and local_root not in sys.path:
            # Prepend local directory so it takes precedence
            sys.path.insert(0, local_root)
            # Clear any cached pm_core imports so we get the local one
            to_remove = [k for k in sys.modules if k == 'pm_core' or k.startswith('pm_core.')]
            for k in to_remove:
                del sys.modules[k]

    # Now import and run the real CLI
    from pm_core.cli import main as cli_main
    return cli_main()


if __name__ == '__main__':
    sys.exit(main())
