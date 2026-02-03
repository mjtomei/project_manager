"""Entry point wrapper that prefers local pm_core when available.

When running from a directory containing pm_core (e.g., a workdir clone),
this wrapper uses the local version instead of the installed one. This
enables testing changes in PR workdirs without reinstalling.
"""
import os
import sys


def find_local_pm_core():
    """Find pm_core in cwd or parent directories."""
    cwd = os.getcwd()
    # Check cwd and up to 3 parent directories
    for _ in range(4):
        candidate = os.path.join(cwd, "pm_core")
        if os.path.isdir(candidate) and os.path.isfile(os.path.join(candidate, "cli.py")):
            return cwd
        parent = os.path.dirname(cwd)
        if parent == cwd:
            break
        cwd = parent
    return None


def main():
    """Entry point that prefers local pm_core."""
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
