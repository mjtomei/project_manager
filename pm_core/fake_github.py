"""In-memory fake GitHub backend for regression tests.

Sibling of FakeClaudeSession (pr-abcf70f): scriptable, deterministic, fast —
for the GitHub side of pm.

The real github backend is exercised end-to-end only against live GitHub: all
`gh` CLI traffic funnels through ``gh_ops.run_gh`` (and the hot-path direct
calls in ``pr_sync`` / ``cli.pr`` were routed through it too). ``run_gh``
exposes a pluggable transport via ``gh_ops.set_gh_runner`` / ``gh_runner``.

``FakeGitHubBackend`` is such a transport: it interprets `gh` argv against
in-memory PR state and returns ``subprocess.CompletedProcess`` objects, so
regression tests can drive PR create / status sync / comments / merges /
post-merge pull without touching the network.

Typical use::

    backend = FakeGitHubBackend()
    with backend.installed():
        gh_ops.create_draft_pr(workdir, "Title", "master", "body")
        ...

or via the ``fake_github`` pytest fixture in ``tests/conftest.py``.

Scripted failures let tests compose realistic flows::

    backend.simulate_rate_limit("pr view")   # next `pr view` returns 403
    backend.simulate_conflict("pr merge")    # next `pr merge` returns a conflict
"""

from __future__ import annotations

import json
import subprocess
from contextlib import contextmanager
from dataclasses import dataclass, field
from typing import Callable, Optional, Union

from pm_core import gh_ops


# --- canned error payloads (mirror real `gh` stderr shapes) -----------------

RATE_LIMIT_STDERR = (
    "gh: API rate limit exceeded for user. "
    "(HTTP 403) Please wait and try again."
)
SERVER_ERROR_STDERR = "gh: Something went wrong (HTTP 502)"
CONFLICT_STDERR = (
    "X Pull request is not mergeable: the merge commit cannot be cleanly "
    "created. Resolve conflicts and try again."
)
NOT_FOUND_STDERR = "gh: Could not resolve to a PullRequest (HTTP 404)"
UNAUTHORIZED_STDERR = "gh: authentication required (HTTP 401)"


@dataclass
class FakePR:
    """A simulated GitHub pull request."""

    number: int
    title: str
    base: str
    head: str
    url: str
    body: str = ""
    state: str = "OPEN"  # OPEN | MERGED | CLOSED
    is_draft: bool = False
    merged_at: Optional[str] = None
    comments: list[str] = field(default_factory=list)

    def to_json(self, fields: list[str]) -> dict:
        """Project the PR onto the requested ``gh --json`` field set."""
        full = {
            "number": self.number,
            "title": self.title,
            "body": self.body,
            "base": self.base,
            "headRefName": self.head,
            "url": self.url,
            "state": self.state,
            "isDraft": self.is_draft,
            "mergedAt": self.merged_at,
        }
        return {k: full[k] for k in fields if k in full}


@dataclass
class _Scripted:
    """A queued canned response that pre-empts normal dispatch."""

    match: Union[str, Callable[[list[str]], bool]]
    returncode: int = 0
    stdout: str = ""
    stderr: str = ""
    remaining: int = 1  # -1 == unlimited

    def matches(self, argv: list[str]) -> bool:
        if callable(self.match):
            return self.match(argv)
        return " ".join(argv).startswith(self.match)


def _completed(argv: list[str], returncode: int, stdout: str = "",
               stderr: str = "") -> subprocess.CompletedProcess:
    return subprocess.CompletedProcess(["gh", *argv], returncode, stdout, stderr)


PRRef = Union[FakePR, str, int]


class FakeGitHubBackend:
    """Scriptable in-memory stand-in for the GitHub side of pm.

    Install it with :meth:`installed` (or the ``fake_github`` fixture) and the
    backend serves every ``gh`` invocation that flows through ``gh_ops``.
    """

    def __init__(self, owner: str = "owner", repo: str = "repo",
                 default_branch: str = "master"):
        self.owner = owner
        self.repo = repo
        self.default_branch = default_branch
        self.prs: dict[int, FakePR] = {}
        self.calls: list[list[str]] = []  # every gh argv, for assertions
        self._next_number = 1
        self._scripts: list[_Scripted] = []

    # --- state seeding ------------------------------------------------------

    def _url(self, number: int) -> str:
        return f"https://github.com/{self.owner}/{self.repo}/pull/{number}"

    def add_pr(self, *, title: str = "Test PR", head: str,
               base: Optional[str] = None, body: str = "",
               is_draft: bool = False, state: str = "OPEN") -> FakePR:
        """Seed a PR directly into simulated remote state."""
        number = self._next_number
        self._next_number += 1
        pr = FakePR(
            number=number,
            title=title,
            base=base or self.default_branch,
            head=head,
            url=self._url(number),
            body=body,
            is_draft=is_draft,
            state=state,
            merged_at="2026-01-01T00:00:00Z" if state == "MERGED" else None,
        )
        self.prs[number] = pr
        return pr

    def resolve(self, ref: PRRef) -> Optional[FakePR]:
        """Resolve a FakePR / number / branch name / 'HEAD' to a FakePR."""
        if isinstance(ref, FakePR):
            return ref
        s = str(ref)
        if s.isdigit():
            return self.prs.get(int(s))
        if s == "HEAD":
            # Newest PR — mirrors gh resolving HEAD to the current branch's PR.
            return self.prs[max(self.prs)] if self.prs else None
        for pr in self.prs.values():
            if pr.head == s:
                return pr
        return None

    # --- simulated remote-state transitions (scenario building blocks) ------

    def create_draft(self, head: str, *, title: str = "Test PR",
                      base: Optional[str] = None, body: str = "") -> FakePR:
        """Simulate the draft PR `pm pr start` opens on the github backend."""
        return self.add_pr(title=title, head=head, base=base, body=body,
                           is_draft=True)

    def mark_ready(self, ref: PRRef) -> FakePR:
        """Simulate the draft -> ready transition `pm pr review` performs."""
        pr = self._require(ref)
        pr.is_draft = False
        return pr

    def merge(self, ref: PRRef) -> FakePR:
        """Simulate the PR being merged on the remote."""
        pr = self._require(ref)
        pr.state = "MERGED"
        pr.is_draft = False
        pr.merged_at = "2026-01-01T00:00:00Z"
        return pr

    def close(self, ref: PRRef) -> FakePR:
        """Simulate the PR being closed (unmerged) on the remote."""
        pr = self._require(ref)
        pr.state = "CLOSED"
        return pr

    def add_comment(self, ref: PRRef, body: str) -> FakePR:
        """Append a comment to a PR."""
        pr = self._require(ref)
        pr.comments.append(body)
        return pr

    def _require(self, ref: PRRef) -> FakePR:
        pr = self.resolve(ref)
        if pr is None:
            raise KeyError(f"no fake PR for ref {ref!r}")
        return pr

    # --- scripted responses -------------------------------------------------

    def queue_response(self, match: Union[str, Callable[[list[str]], bool]],
                        *, returncode: int = 0, stdout: str = "",
                        stderr: str = "", times: int = 1) -> None:
        """Queue a canned response for commands matching ``match``.

        ``match`` is either a prefix of the space-joined `gh` argv
        (e.g. ``"pr merge"``) or a predicate over the argv list. Queued
        responses are consumed FIFO; ``times=-1`` makes one persist.
        """
        self._scripts.append(
            _Scripted(match, returncode, stdout, stderr, times)
        )

    def simulate_rate_limit(self, match: str, *, times: int = 1) -> None:
        """Next matching command(s) fail with a GitHub rate-limit (HTTP 403)."""
        self.queue_response(match, returncode=1, stderr=RATE_LIMIT_STDERR,
                            times=times)

    def simulate_server_error(self, match: str, *, times: int = 1) -> None:
        """Next matching command(s) fail with a 5xx server error."""
        self.queue_response(match, returncode=1, stderr=SERVER_ERROR_STDERR,
                            times=times)

    def simulate_conflict(self, match: str, *, times: int = 1) -> None:
        """Next matching command(s) fail with a merge-conflict error."""
        self.queue_response(match, returncode=1, stderr=CONFLICT_STDERR,
                            times=times)

    def simulate_not_found(self, match: str, *, times: int = 1) -> None:
        """Next matching command(s) fail with a 404."""
        self.queue_response(match, returncode=1, stderr=NOT_FOUND_STDERR,
                            times=times)

    def clear_scripts(self) -> None:
        """Drop all queued scripted responses."""
        self._scripts.clear()

    # --- transport ----------------------------------------------------------

    def run(self, argv: list[str],
            cwd: Optional[str] = None) -> subprocess.CompletedProcess:
        """Interpret a `gh` invocation (argv without the leading ``gh``)."""
        self.calls.append(list(argv))

        for i, scr in enumerate(self._scripts):
            if scr.matches(argv):
                if scr.remaining > 0:
                    scr.remaining -= 1
                    if scr.remaining == 0:
                        self._scripts.pop(i)
                return _completed(argv, scr.returncode, scr.stdout, scr.stderr)

        if not argv:
            return _completed(argv, 1, "", "fake-gh: empty command")
        if argv[0] == "auth":
            return _completed(argv, 0, "Logged in to github.com (fake)\n", "")
        if argv[0] == "pr":
            return self._dispatch_pr(argv[1:])
        return _completed(argv, 1, "",
                          f"fake-gh: unsupported command: {' '.join(argv)}")

    @contextmanager
    def installed(self):
        """Context manager: install this fake as the gh transport."""
        with gh_ops.gh_runner(self.run):
            yield self

    # --- `gh pr ...` dispatch ----------------------------------------------

    def _dispatch_pr(self, args: list[str]) -> subprocess.CompletedProcess:
        if not args:
            return _completed(["pr"], 1, "", "fake-gh: `gh pr` needs a subcommand")
        sub, rest = args[0], args[1:]
        pos, opts = _parse_opts(rest)
        handler = {
            "create": self._pr_create,
            "view": self._pr_view,
            "list": self._pr_list,
            "ready": self._pr_ready,
            "merge": self._pr_merge,
            "close": self._pr_close,
            "comment": self._pr_comment,
        }.get(sub)
        if handler is None:
            return _completed(["pr", sub], 1, "",
                              f"fake-gh: unsupported `gh pr {sub}`")
        return handler(pos, opts)

    def _pr_create(self, pos, opts):
        pr = self.add_pr(
            title=opts.get("--title", "Untitled"),
            base=opts.get("--base", self.default_branch),
            head=opts.get("--head", f"branch-{self._next_number}"),
            body=opts.get("--body", ""),
            is_draft="--draft" in opts,
        )
        return _completed(["pr", "create"], 0, pr.url + "\n", "")

    def _pr_view(self, pos, opts):
        ref = pos[0] if pos else "HEAD"
        pr = self.resolve(ref)
        if pr is None:
            return _completed(["pr", "view"], 1, "", NOT_FOUND_STDERR)
        fields_opt = opts.get("--json")
        if not fields_opt:
            # Human-readable mode; pm always uses --json, so keep it minimal.
            return _completed(["pr", "view"], 0,
                              f"#{pr.number} {pr.title}\n", "")
        fields = [f.strip() for f in fields_opt.split(",") if f.strip()]
        return _completed(["pr", "view"], 0,
                          json.dumps(pr.to_json(fields)) + "\n", "")

    def _pr_list(self, pos, opts):
        state = opts.get("--state", "open").upper()
        fields_opt = opts.get("--json") or "number,title,headRefName,state,url"
        fields = [f.strip() for f in fields_opt.split(",") if f.strip()]
        items = [
            pr.to_json(fields)
            for pr in sorted(self.prs.values(), key=lambda p: p.number)
            if state == "ALL" or pr.state == state
        ]
        return _completed(["pr", "list"], 0, json.dumps(items) + "\n", "")

    def _pr_ready(self, pos, opts):
        pr = self.resolve(pos[0]) if pos else None
        if pr is None:
            return _completed(["pr", "ready"], 1, "", NOT_FOUND_STDERR)
        pr.is_draft = False
        return _completed(["pr", "ready"], 0,
                          f"PR #{pr.number} marked ready\n", "")

    def _pr_merge(self, pos, opts):
        pr = self.resolve(pos[0]) if pos else None
        if pr is None:
            return _completed(["pr", "merge"], 1, "", NOT_FOUND_STDERR)
        if pr.state == "MERGED":
            # merged-elsewhere: gh exits non-zero; pm's is_pr_merged fallback
            # then recognises the already-merged state.
            return _completed(["pr", "merge"], 1, "",
                              f"X Pull request #{pr.number} is already merged")
        if pr.state == "CLOSED":
            return _completed(["pr", "merge"], 1, "",
                              f"X Pull request #{pr.number} is closed")
        self.merge(pr)
        return _completed(["pr", "merge"], 0,
                          f"X Merged pull request #{pr.number}\n", "")

    def _pr_close(self, pos, opts):
        pr = self.resolve(pos[0]) if pos else None
        if pr is None:
            return _completed(["pr", "close"], 1, "", NOT_FOUND_STDERR)
        if pr.state != "MERGED":
            pr.state = "CLOSED"
        return _completed(["pr", "close"], 0,
                          f"X Closed pull request #{pr.number}\n", "")

    def _pr_comment(self, pos, opts):
        pr = self.resolve(pos[0]) if pos else None
        if pr is None:
            return _completed(["pr", "comment"], 1, "", NOT_FOUND_STDERR)
        pr.comments.append(opts.get("--body", ""))
        return _completed(["pr", "comment"], 0, pr.url + "\n", "")


def _parse_opts(args: list[str]) -> tuple[list[str], dict]:
    """Split `gh` args into (positionals, options).

    Known value-taking flags consume the next token; everything else starting
    with ``-`` is a boolean flag.
    """
    valued = {"--title", "--base", "--body", "--head", "--json",
              "--state", "--repo", "-R"}
    pos: list[str] = []
    opts: dict = {}
    i = 0
    while i < len(args):
        a = args[i]
        if a.startswith("-"):
            if a in valued and i + 1 < len(args):
                opts[a] = args[i + 1]
                i += 2
            else:
                opts[a] = True
                i += 1
        else:
            pos.append(a)
            i += 1
    return pos, opts


# --- named scenario helpers -------------------------------------------------
#
# These compose the state transitions above into the flows the regression
# runner replays. Each returns the FakePR involved so tests can assert on it.

def create_draft_on_start(backend: FakeGitHubBackend, branch: str,
                          *, title: str = "Test PR",
                          base: Optional[str] = None) -> FakePR:
    """Scenario: `pm pr start` opens a draft PR on the github backend."""
    return backend.create_draft(branch, title=title, base=base)


def upgrade_on_done(backend: FakeGitHubBackend, ref: PRRef) -> FakePR:
    """Scenario: `pm pr review` upgrades the draft PR to ready-for-review."""
    return backend.mark_ready(ref)


def merge_with_pull(backend: FakeGitHubBackend, ref: PRRef) -> FakePR:
    """Scenario: the PR is merged remotely; `pm pr merge` then pulls base."""
    return backend.merge(ref)


def sync_mid_flow(backend: FakeGitHubBackend, ref: PRRef,
                  *, state: str) -> FakePR:
    """Scenario: advance simulated remote state mid-flow (sync-race tests).

    ``state`` is one of ``OPEN`` / ``MERGED`` / ``CLOSED``; a subsequent
    ``pr_sync.sync_from_github`` poll will observe the new state.
    """
    pr = backend._require(ref)
    if state == "MERGED":
        backend.merge(pr)
    elif state == "CLOSED":
        backend.close(pr)
    elif state == "OPEN":
        pr.state = "OPEN"
        pr.merged_at = None
    else:
        raise ValueError(f"unknown state {state!r}")
    return pr
