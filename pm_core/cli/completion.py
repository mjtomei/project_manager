"""Tab completion for pm command lines.

The prefix+M popup (through stdlib ``readline``) and the TUI command bar
share one completer.  :meth:`PmCompleter.complete_line` takes the text
before the cursor and returns where the word being completed starts plus
the candidates for it:

- subcommand names at any depth, read from Click's command tree, so new
  commands complete without changes here (hidden ``_internal`` commands
  are skipped);
- option names of the resolved command;
- PR IDs, both internal ``pr-xxxxxxx`` and GitHub ``#N``, for ``pr_id``
  arguments and the ``--depends-on`` / ``--pr`` options (``--depends-on``
  takes a comma-separated list);
- plan IDs for ``plan_id`` arguments and ``--plan``;
- the values of ``click.Choice`` parameters.

PR and plan IDs come from the session's ``project.yaml`` and reload when
its signature changes, so a PR added while the popup is open completes at
the next Tab.
"""

from __future__ import annotations

import re
import shlex
from pathlib import Path

import click

from pm_core import store
from pm_core.command_history import file_signature
from pm_core.paths import configure_logger

_log = configure_logger("pm.cli.completion")

# Argument / option names whose values are PR or plan IDs.
_PR_ARG_NAMES = {"pr_id", "identifier"}
_PLAN_ARG_NAMES = {"plan_id"}
_PR_OPTIONS = {"--depends-on", "--pr"}
_LIST_OPTIONS = {"--depends-on"}  # comma-separated values
_PLAN_OPTIONS = {"--plan"}

# Top-level words the popup and the TUI bar accept that are not Click
# commands: ``review-loop [start] [PR_ID]`` is routed to the TUI.
_EXTRA_TOP_LEVEL = ("review-loop",)

_WORD_RE = re.compile(r"\S*$")


def _public_commands(group: click.Group) -> list[str]:
    return sorted(name for name, cmd in group.commands.items()
                  if not name.startswith("_") and not getattr(cmd, "hidden", False))


def _find_option(cmd: click.Command, name: str) -> click.Option | None:
    for p in cmd.params:
        if isinstance(p, click.Option) and name in (*p.opts, *p.secondary_opts):
            return p
    return None


def _takes_value(opt: click.Option) -> bool:
    return not (opt.is_flag or opt.count)


class PmCompleter:
    """Completes pm command lines against the Click tree and project.yaml.

    *root* is the directory holding the session's ``project.yaml`` (the
    persisted pm root); with None only commands and options complete.
    """

    def __init__(self, root: Path | None, group: click.Group | None = None):
        self.root = Path(root) if root is not None else None
        self._group = group
        self._data_sig: object = None
        self._loaded = False
        self._pr_ids: list[str] = []
        self._plan_ids: list[str] = []
        self._matches: list[str] = []

    # --- data sources -----------------------------------------------------

    @property
    def group(self) -> click.Group:
        if self._group is None:
            from pm_core.cli import cli
            self._group = cli
        return self._group

    def _ensure_ids(self) -> None:
        if self.root is None:
            return
        sig = file_signature(self.root / "project.yaml")
        if self._loaded and sig == self._data_sig:
            return
        self._data_sig = sig
        self._loaded = True
        try:
            data = store.load(self.root, validate=False)
        except Exception as e:  # malformed/missing yaml: keep what we had
            _log.info("completion: project.yaml unavailable (%s): %s", self.root, e)
            return
        prs = [p for p in data.get("prs") or [] if isinstance(p, dict)]
        internal = sorted(str(p["id"]) for p in prs if p.get("id"))
        numbered = sorted({int(p["gh_pr_number"]) for p in prs
                           if isinstance(p.get("gh_pr_number"), int)})
        self._pr_ids = [f"#{n}" for n in numbered] + internal
        self._plan_ids = sorted(str(p["id"]) for p in data.get("plans") or []
                                if isinstance(p, dict) and p.get("id"))

    def pr_ids(self) -> list[str]:
        self._ensure_ids()
        return list(self._pr_ids)

    def plan_ids(self) -> list[str]:
        self._ensure_ids()
        return list(self._plan_ids)

    # --- core -------------------------------------------------------------

    def complete_line(self, line: str) -> tuple[int, list[str]]:
        """Complete the last word of *line* (the text before the cursor).

        Returns ``(start, matches)``: the index in *line* where that word
        begins, and the full replacement words that extend it, in
        display order.  Never raises.
        """
        start = _WORD_RE.search(line).start()
        text = line[start:]
        before = line[:start]
        try:
            prior = shlex.split(before)
        except ValueError:  # unbalanced quote before the cursor
            prior = before.split()
        try:
            cands = self._candidates(prior, text)
        except Exception:
            _log.exception("completion failed for %r", line)
            cands = []
        seen: set[str] = set()
        out = []
        for c in cands:
            if c.startswith(text) and c not in seen:
                seen.add(c)
                out.append(c)
        return start, out

    def _candidates(self, prior: list[str], text: str) -> list[str]:
        if prior and prior[0] in _EXTRA_TOP_LEVEL:
            # review-loop [start] [PR_ID]
            rest = [t for t in prior[1:] if not t.startswith("-")]
            if not rest:
                return ["start"] + self.pr_ids()
            if rest == ["start"]:
                return self.pr_ids()
            return []

        node: click.Command = self.group
        positional = 0
        pending: click.Option | None = None
        for tok in prior:
            if pending is not None:
                pending = None
                continue
            if tok.startswith("-") and tok != "-":
                name, eq, _ = tok.partition("=")
                opt = _find_option(node, name)
                if opt is not None and _takes_value(opt) and not eq:
                    pending = opt
                continue
            if isinstance(node, click.Group):
                sub = node.commands.get(tok)
                if sub is None:
                    return []
                node = sub
                positional = 0
            else:
                positional += 1

        if pending is not None:
            return self._option_values(pending, text)
        if text.startswith("-"):
            name, eq, value = text.partition("=")
            if eq:
                opt = _find_option(node, name)
                if opt is None:
                    return []
                return [f"{name}={v}" for v in self._option_values(opt, value)]
            opts = [o for p in node.params if isinstance(p, click.Option)
                    if not getattr(p, "hidden", False)
                    for o in (*p.opts, *p.secondary_opts)]
            return sorted(set(opts) | {"--help"})
        if isinstance(node, click.Group):
            names = _public_commands(node)
            if node is self.group:
                names = sorted(set(names) | set(_EXTRA_TOP_LEVEL))
            return names
        return self._argument_values(node, positional)

    def _argument_values(self, cmd: click.Command, index: int) -> list[str]:
        args = [p for p in cmd.params if isinstance(p, click.Argument)]
        param = None
        for i, a in enumerate(args):
            if i == index or a.nargs == -1 and i <= index:
                param = a
                break
        if param is None:
            return []
        return self._param_values(param)

    def _param_values(self, param: click.Parameter) -> list[str]:
        if isinstance(param.type, click.Choice):
            return [str(c) for c in param.type.choices]
        if param.name in _PR_ARG_NAMES:
            return self.pr_ids()
        if param.name in _PLAN_ARG_NAMES:
            return self.plan_ids()
        return []

    def _option_values(self, opt: click.Option, value: str) -> list[str]:
        names = set(opt.opts)
        if names & _PR_OPTIONS:
            ids = self.pr_ids()
        elif names & _PLAN_OPTIONS:
            ids = self.plan_ids()
        else:
            return self._param_values(opt)
        if names & _LIST_OPTIONS and "," in value:
            head = value[:value.rindex(",") + 1]
            return [head + i for i in ids]
        return ids

    # --- readline glue ----------------------------------------------------

    def readline_complete(self, text: str, state: int) -> str | None:
        """``readline.set_completer`` hook (word delimiters: whitespace)."""
        if state == 0:
            try:
                import readline
                line = readline.get_line_buffer()[:readline.get_endidx()]
            except Exception:
                line = text
            self._matches = self.complete_line(line)[1]
        return self._matches[state] if state < len(self._matches) else None


def common_prefix(words: list[str]) -> str:
    """Longest common prefix of *words* ('' for none)."""
    if not words:
        return ""
    lo, hi = min(words), max(words)
    i = 0
    while i < len(lo) and lo[i] == hi[i]:
        i += 1
    return lo[:i]
