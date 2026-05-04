"""Tab-completion helpers for the pm popup shell.

The completer plugs into stdlib ``readline``. It completes:

- top-level pm subcommands (from the Click command tree),
- PR IDs (internal ``pr-xxxxxx`` and ``#<gh_pr>`` aliases),
- plan IDs.

It is loaded once per popup invocation; PR/plan IDs are read from
``project.yaml`` via ``store.load`` and refreshed lazily on demand.
"""

from __future__ import annotations

import shlex
from pathlib import Path

from pm_core import store


# Subcommands whose first positional arg is a PR ID.
_PR_VERBS = {
    "pr",          # `pr <id>` and `pr <subcmd> <id>`
    "review-loop", # `review-loop start <id>`
    "edit",
    "show",
    "qa",
}

_PLAN_VERBS = {"plan"}


def _public_subcommands() -> list[str]:
    """Return non-hidden top-level pm subcommand names."""
    try:
        from pm_core.cli.session import cli
    except Exception:
        return []
    out = []
    for name, cmd in cli.commands.items():
        if name.startswith("_"):
            continue
        if getattr(cmd, "hidden", False):
            continue
        out.append(name)
    return sorted(out)


class PmCompleter:
    """Readline completer for the pm popup."""

    def __init__(self, saved_root: Path | None):
        self.saved_root = saved_root
        self._matches: list[str] = []
        self._cmds = _public_subcommands()
        self._pr_ids: list[str] | None = None
        self._plan_ids: list[str] | None = None

    # --- data sources -----------------------------------------------------

    def _load_ids(self) -> None:
        if self._pr_ids is not None:
            return
        self._pr_ids = []
        self._plan_ids = []
        if self.saved_root is None:
            return
        try:
            data = store.load(self.saved_root, validate=False)
        except Exception:
            return
        for pr in data.get("prs", []) or []:
            pid = pr.get("id")
            if pid:
                self._pr_ids.append(pid)
            gh = pr.get("gh_pr")
            if gh:
                self._pr_ids.append(f"#{gh}")
        for plan in data.get("plans", []) or []:
            pid = plan.get("id")
            if pid:
                self._plan_ids.append(pid)

    def pr_ids(self) -> list[str]:
        self._load_ids()
        return self._pr_ids or []

    def plan_ids(self) -> list[str]:
        self._load_ids()
        return self._plan_ids or []

    # --- readline interface ----------------------------------------------

    def complete(self, text: str, state: int):
        if state == 0:
            self._matches = self._compute_matches(text)
        if state < len(self._matches):
            return self._matches[state]
        return None

    def _compute_matches(self, text: str) -> list[str]:
        try:
            import readline
        except ImportError:
            return []
        line = readline.get_line_buffer()
        begin = readline.get_begidx()
        # Tokenize the line up to the cursor; trailing partial token = text.
        before = line[:begin]
        try:
            prior_tokens = shlex.split(before) if before.strip() else []
        except ValueError:
            prior_tokens = before.split()

        candidates = self._candidates(prior_tokens, text)
        return [c for c in candidates if c.startswith(text)]

    def _candidates(self, prior: list[str], text: str) -> list[str]:
        # Flag-value completions take precedence.
        if text.startswith("--"):
            return ["--plan=", "--depends-on=", "--help"]
        if prior:
            last = prior[-1]
            if last in ("--plan", "--depends-on") or last.endswith("="):
                if last.startswith("--plan"):
                    return self.plan_ids()
                if last.startswith("--depends-on"):
                    return self.pr_ids()

        # No prior tokens -> top-level subcommand.
        if not prior:
            return self._cmds

        head = prior[0]
        if head in _PLAN_VERBS:
            return self._plan_or_subcmd(prior)
        if head in _PR_VERBS:
            return self._pr_or_subcmd(prior)
        # Unknown verb: still offer PR IDs (covers aliases).
        return self.pr_ids()

    def _pr_or_subcmd(self, prior: list[str]) -> list[str]:
        # Position-2 token may be a subcommand keyword (edit/show/qa/...) or a PR ID.
        if len(prior) == 1:
            return ["edit", "show", "qa", "review", "list", "start", "done"] + self.pr_ids()
        return self.pr_ids()

    def _plan_or_subcmd(self, prior: list[str]) -> list[str]:
        if len(prior) == 1:
            return ["add", "list", "show", "breakdown", "review"] + self.plan_ids()
        return self.plan_ids()


def install(saved_root: Path | None) -> PmCompleter | None:
    """Configure readline with a fresh ``PmCompleter`` and return it.

    Returns None if readline is unavailable on this platform.
    """
    try:
        import readline
    except ImportError:
        return None
    completer = PmCompleter(saved_root)
    readline.set_completer(completer.complete)
    readline.set_completer_delims(" \t\n")
    readline.parse_and_bind("tab: complete")
    return completer
