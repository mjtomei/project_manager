"""Fake GitHub backend for regression tests.

Sibling of FakeClaudeSession (pr-abcf70f): scriptable, deterministic, fast —
for the GitHub side of pm.

The real github backend is exercised end-to-end only against live GitHub: all
`gh` CLI traffic funnels through ``gh_ops.run_gh`` (every direct
``subprocess.run(["gh", ...])`` call in pm was routed through it too).
``run_gh`` exposes a pluggable transport via ``gh_ops.set_gh_runner`` /
``gh_runner``.

``FakeGitHubBackend`` is such a transport: it interprets `gh` argv and returns
``subprocess.CompletedProcess`` objects, so regression tests can drive PR
create / status sync / comments / merges / post-merge pull without touching
the network.

**Git backing.** A `pm pr merge` on the github backend has two halves: the
GitHub-API call (`gh pr merge`) and the git plumbing that follows
(`git fetch` / `git merge --ff-only`, via ``_pull_after_merge``). So the
*git-affecting* `gh` operations are backed by a real local git repo
(:class:`FakeGitHubRepo`) acting as the remote: `gh pr create` ensures the
head branch exists, `gh pr merge` actually merges it into the base branch, so
a downstream `git fetch` + `git merge --ff-only` fast-forwards cleanly.
Operations that do not affect git history — `gh pr comment`, repo admin — stay
pure in-memory metadata (deferred; see pm/specs/pr-9603d04/impl.md, R8).

Typical use::

    # pure-metadata fake (no git operations needed)
    backend = FakeGitHubBackend()
    with backend.installed():
        gh_ops.create_draft_pr(workdir, "Title", "master", "body")

    # git-backed fake (merge-with-pull and other git-affecting flows)
    backend = FakeGitHubBackend.with_git_repo(tmp_path)
    with backend.installed():
        ...

or via the ``fake_github`` / ``fake_github_repo`` pytest fixtures in
``tests/conftest.py``.

Scripted failures let tests compose realistic flows::

    backend.simulate_rate_limit("pr view")   # next `pr view` returns 403
    backend.simulate_conflict("pr merge")    # next `pr merge` returns a conflict
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import threading
from contextlib import contextmanager
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Callable, Optional, Union

from pm_core import gh_ops


def _resolve_real_git() -> str:
    """Locate the real `git` binary, bypassing any pm push-proxy wrapper.

    Sandboxed pm workdirs put a `git` shell wrapper early on PATH that
    forwards remote commands (push/fetch/pull/ls-remote) to a host-side
    proxy. FakeGitHubRepo only ever operates on a purely local repo, so it
    must use the real binary directly — otherwise `git fetch` from a consumer
    clone would be hijacked away from the fake remote.
    """
    for cand in ("/usr/bin/git", "/bin/git"):
        if os.path.exists(cand):
            return cand
    return shutil.which("git") or "git"


#: Path to the real git binary (see _resolve_real_git). Exported so tests
#: driving a consumer clone of a FakeGitHubRepo can bypass the wrapper too.
REAL_GIT = _resolve_real_git()


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


# --- git-backed remote ------------------------------------------------------

class FakeGitHubRepo:
    """A real local git repo standing in for the GitHub-side remote.

    ``path`` is an ordinary (non-bare) git repo usable directly as a git
    ``origin`` for ``git clone`` / ``git fetch``. Branch and merge mutations
    are performed in place, so the git-affecting `gh` operations produce
    genuine git history that a downstream ``git fetch`` / ``git merge
    --ff-only`` can consume.

    Implementation note: all mutations are local (init / commit / checkout /
    merge) — the fake never runs ``git push``, so it works inside sandboxed
    environments whose push is proxied/restricted.
    """

    def __init__(self, path: Union[str, Path], default_branch: str = "master"):
        self.path = str(path)
        self.default_branch = default_branch
        # The repo is a single non-bare worktree, so every branch/merge mutation
        # touches the shared index. Serialize them: concurrent merges would
        # otherwise collide on .git/index.lock and lose work. Re-entrant so a
        # mutation built from sub-steps can hold it across them.
        self._lock = threading.RLock()
        self._init()

    # -- low-level git -------------------------------------------------------

    def _git(self, *args: str, check: bool = True) -> subprocess.CompletedProcess:
        result = subprocess.run(
            [REAL_GIT, *args], cwd=self.path, capture_output=True, text=True,
        )
        if check and result.returncode != 0:
            raise RuntimeError(
                f"git {' '.join(args)} failed in {self.path}: "
                f"{result.stderr.strip()}"
            )
        return result

    def _init(self) -> None:
        """Create the remote repo with an initial commit on the base branch.

        Idempotent: if the repo already exists on disk (re-attaching to an
        out-of-process session's ``remote.git/``), leave it untouched.
        """
        Path(self.path).mkdir(parents=True, exist_ok=True)
        if (Path(self.path) / ".git").exists():
            return
        self._git("init", "-b", self.default_branch)
        self._git("config", "user.email", "fake-gh@example.com")
        self._git("config", "user.name", "Fake GitHub")
        self._git("config", "commit.gpgsign", "false")
        Path(self.path, "README.md").write_text("fake github remote\n")
        self._git("add", "README.md")
        self._git("commit", "-m", "initial commit")

    # -- queries -------------------------------------------------------------

    def branch_exists(self, name: str) -> bool:
        result = self._git("rev-parse", "--verify", "--quiet",
                           f"refs/heads/{name}", check=False)
        return result.returncode == 0

    def is_merged(self, head: str, base: Optional[str] = None) -> bool:
        """True if ``head``'s tip is an ancestor of ``base``."""
        base = base or self.default_branch
        result = self._git("merge-base", "--is-ancestor", head, base,
                           check=False)
        return result.returncode == 0

    # -- mutations -----------------------------------------------------------

    def ensure_branch(self, name: str, *, base: Optional[str] = None,
                      files: Optional[dict[str, str]] = None) -> None:
        """Create branch ``name`` (forked from ``base``) if it is absent.

        ``files`` maps repo-relative paths to contents committed on the new
        branch; the default is a unique marker file so the branch is one
        commit ahead of base (a mergeable PR). Existing branches are left
        untouched.
        """
        base = base or self.default_branch
        with self._lock:
            if name == base or self.branch_exists(name):
                return
            self._git("checkout", "-b", name, base)
            payload = files or {f".pr-{name}": f"branch {name}\n"}
            for rel, content in payload.items():
                dest = Path(self.path, rel)
                dest.parent.mkdir(parents=True, exist_ok=True)
                dest.write_text(content)
                self._git("add", rel)
            self._git("commit", "-m", f"work on {name}")
            self._git("checkout", base)

    def merge_branch(self, head: str,
                     base: Optional[str] = None) -> tuple[bool, str]:
        """Merge ``head`` into ``base``.

        Returns ``(ok, detail)``. On a real git conflict ``ok`` is False and
        ``base`` is left unchanged — the caller surfaces a conflict-shaped
        `gh` failure.

        Concurrency-safe: the whole merge sequence runs under ``self._lock`` so
        parallel merges into the single backing worktree serialize instead of
        colliding on ``.git/index.lock``. Every git step uses ``check=False`` and
        the worktree is restored to a clean state on any failure, so a losing
        merge never escapes as an unhandled ``RuntimeError`` nor leaves a
        dangling ``MERGE_HEAD`` / stale ``index.lock`` behind.
        """
        base = base or self.default_branch
        with self._lock:
            if not self.branch_exists(head):
                return False, f"head branch {head!r} does not exist"
            checkout = self._git("checkout", base, check=False)
            if checkout.returncode != 0:
                self._cleanup_worktree()
                return False, (checkout.stdout + checkout.stderr).strip()
            merge = self._git("merge", "--no-ff", "--no-edit", head, check=False)
            if merge.returncode != 0:
                detail = (merge.stdout + merge.stderr).strip()
                self._git("merge", "--abort", check=False)
                self._cleanup_worktree()
                return False, detail
            return True, ""

    def _cleanup_worktree(self) -> None:
        """Best-effort scrub of a half-finished merge's leftover state.

        Removes a dangling ``.git/MERGE_HEAD`` (an aborted/failed merge) and a
        stale ``.git/index.lock`` so the backing repo is left usable for the
        next operation and for a consumer ``git fetch`` / ``merge --ff-only``.
        """
        git_dir = Path(self.path, ".git")
        for leftover in ("MERGE_HEAD", "index.lock"):
            try:
                (git_dir / leftover).unlink()
            except FileNotFoundError:
                pass
            except OSError:
                pass

    def clone(self, dest: Union[str, Path]) -> str:
        """Clone the remote to ``dest`` — a consumer workdir for tests."""
        dest = str(dest)
        Path(dest).parent.mkdir(parents=True, exist_ok=True)
        subprocess.run([REAL_GIT, "clone", self.path, dest],
                       capture_output=True, text=True, check=True)
        return dest


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
    """Scriptable stand-in for the GitHub side of pm.

    Install it with :meth:`installed` (or a fixture) and the backend serves
    every ``gh`` invocation that flows through ``gh_ops``. Pass ``git_repo``
    (or build via :meth:`with_git_repo`) so the git-affecting operations are
    backed by a real repo.
    """

    def __init__(self, owner: str = "owner", repo: str = "repo",
                 default_branch: str = "master",
                 git_repo: Optional[FakeGitHubRepo] = None):
        self.owner = owner
        self.repo = repo
        self.default_branch = default_branch
        self.git_repo = git_repo
        self.prs: dict[int, FakePR] = {}
        self.calls: list[list[str]] = []  # every gh argv, for assertions
        self._next_number = 1
        self._scripts: list[_Scripted] = []
        # Guards scripted-response matching/consumption so a single queued
        # response (times=1) is served to at most one of several racing calls.
        self._scripts_lock = threading.Lock()

    @classmethod
    def with_git_repo(cls, base_path: Union[str, Path], *,
                      owner: str = "owner", repo: str = "repo",
                      default_branch: str = "master") -> "FakeGitHubBackend":
        """Build a git-backed fake: a real :class:`FakeGitHubRepo` remote."""
        git_repo = FakeGitHubRepo(
            Path(base_path) / "remote.git", default_branch=default_branch,
        )
        return cls(owner=owner, repo=repo, default_branch=default_branch,
                   git_repo=git_repo)

    # --- serialization (out-of-process session state) -----------------------

    def to_state(self) -> dict:
        """Serialize registry + scripts for the on-disk session fake.

        Predicate (callable) scripts are in-process only and are dropped — a
        subprocess can only carry string-prefix matches.
        """
        return {
            "owner": self.owner,
            "repo": self.repo,
            "default_branch": self.default_branch,
            "git_backed": self.git_repo is not None,
            "next_number": self._next_number,
            "prs": [asdict(pr) for pr in self.prs.values()],
            "scripts": [
                {"match": s.match, "returncode": s.returncode,
                 "stdout": s.stdout, "stderr": s.stderr,
                 "remaining": s.remaining}
                for s in self._scripts if isinstance(s.match, str)
            ],
        }

    @classmethod
    def from_state(cls, state: dict,
                   git_repo: Optional[FakeGitHubRepo] = None) -> "FakeGitHubBackend":
        """Rebuild a backend from :meth:`to_state` output (does not re-seed git)."""
        b = cls(
            owner=state.get("owner", "owner"),
            repo=state.get("repo", "repo"),
            default_branch=state.get("default_branch", "master"),
            git_repo=git_repo,
        )
        b._next_number = state.get("next_number", 1)
        for prd in state.get("prs", []):
            pr = FakePR(**prd)
            b.prs[pr.number] = pr
        for sd in state.get("scripts", []):
            b._scripts.append(_Scripted(
                match=sd["match"], returncode=sd.get("returncode", 0),
                stdout=sd.get("stdout", ""), stderr=sd.get("stderr", ""),
                remaining=sd.get("remaining", 1)))
        return b

    # --- state seeding ------------------------------------------------------

    def _url(self, number: int) -> str:
        return f"https://github.com/{self.owner}/{self.repo}/pull/{number}"

    def add_pr(self, *, title: str = "Test PR", head: str,
               base: Optional[str] = None, body: str = "",
               is_draft: bool = False, state: str = "OPEN",
               files: Optional[dict[str, str]] = None) -> FakePR:
        """Seed a PR into simulated remote state.

        When git-backed, the head branch is created in the backing repo
        (``files`` lets tests craft branch contents — e.g. for conflicts),
        and ``state="MERGED"`` performs a real merge.
        """
        number = self._next_number
        self._next_number += 1
        base = base or self.default_branch
        pr = FakePR(
            number=number, title=title, base=base, head=head,
            url=self._url(number), body=body, is_draft=is_draft, state="OPEN",
        )
        self.prs[number] = pr
        if self.git_repo is not None:
            self.git_repo.ensure_branch(head, base=base, files=files)
        if state == "MERGED":
            self.merge(pr)
        elif state == "CLOSED":
            pr.state = "CLOSED"
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
                      base: Optional[str] = None, body: str = "",
                      files: Optional[dict[str, str]] = None) -> FakePR:
        """Simulate the draft PR `pm pr start` opens on the github backend."""
        return self.add_pr(title=title, head=head, base=base, body=body,
                           is_draft=True, files=files)

    def mark_ready(self, ref: PRRef) -> FakePR:
        """Simulate the draft -> ready transition `pm pr review` performs."""
        pr = self._require(ref)
        pr.is_draft = False
        return pr

    def _do_merge(self, pr: FakePR) -> tuple[bool, str]:
        """Perform the merge (real git when git-backed). Returns (ok, detail)."""
        if self.git_repo is not None:
            return self.git_repo.merge_branch(pr.head, pr.base)
        return True, ""

    def merge(self, ref: PRRef) -> FakePR:
        """Simulate the PR being merged on the remote.

        When git-backed this performs a real merge; a conflict raises
        ``RuntimeError`` (use ``gh pr merge`` / :meth:`simulate_conflict` to
        exercise conflict *handling* — this helper is for the happy path).
        """
        pr = self._require(ref)
        ok, detail = self._do_merge(pr)
        if not ok:
            raise RuntimeError(f"cannot merge PR #{pr.number}: {detail}")
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
        """Append a comment to a PR (pure metadata — not git-backed)."""
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

        with self._scripts_lock:
            for i, scr in enumerate(self._scripts):
                if scr.matches(argv):
                    if scr.remaining > 0:
                        scr.remaining -= 1
                        if scr.remaining == 0:
                            self._scripts.pop(i)
                    return _completed(argv, scr.returncode, scr.stdout,
                                      scr.stderr)

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
        ok, detail = self._do_merge(pr)
        if not ok:
            # A real git conflict in the backing repo -> conflict-shaped fail.
            return _completed(["pr", "merge"], 1, "",
                              f"{CONFLICT_STDERR}\n{detail}")
        pr.state = "MERGED"
        pr.is_draft = False
        pr.merged_at = "2026-01-01T00:00:00Z"
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
    """Scenario: the PR is merged remotely; `pm pr merge` then pulls base.

    With a git-backed fake the base branch genuinely advances, so a consumer
    workdir cloned from ``backend.git_repo`` can `git fetch` + `git merge
    --ff-only` to complete the pull half.
    """
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


# --- out-of-process session installer ---------------------------------------
#
# Mirrors fake-claude's per-session config gate. `install_session` seeds the
# fake into ~/.pm/sessions/<tag>/fake-github/ (state.json + remote.git/);
# thereafter any `gh` command pm runs in that session — even from a freshly
# spawned `pm pr ...` subprocess — is served by the fake, because
# `gh_ops.run_gh` consults `paths.fake_github_active()` and calls
# `dispatch_session`. State is reloaded and persisted around each command so it
# survives across subprocess boundaries.
#
# Concurrency note: dispatch assumes a session's `gh` calls are serial (true
# for pm flows — a single pane runs them one at a time). The in-process path
# (FakeGitHubBackend.installed) remains the route for multi-threaded tests.

def install_session(config: dict, session_tag: Optional[str] = None) -> FakeGitHubBackend:
    """Seed an out-of-process fake-github for a pm session.

    ``config`` is a plain dict (JSON-friendly)::

        {
          "git_backed": true,              # default true
          "default_branch": "master",
          "owner": "owner", "repo": "repo",
          "prs": [
            {"head": "feat-x", "title": "...", "draft": true,
             "base": "master", "state": "OPEN", "files": {"a.txt": "..."}}
          ],
          "scripts": [
            {"match": "pr merge", "returncode": 1, "stderr": "...", "times": 1}
          ]
        }

    Returns the seeded backend (already persisted to disk).
    """
    from pm_core import paths
    d = paths.fake_github_dir(session_tag)
    if d is None:
        raise RuntimeError("no pm session tag: cannot install fake-github")
    d.mkdir(parents=True, exist_ok=True)

    git_backed = config.get("git_backed", True)
    default_branch = config.get("default_branch", "master")
    git_repo = (FakeGitHubRepo(d / "remote.git", default_branch)
                if git_backed else None)
    backend = FakeGitHubBackend(
        owner=config.get("owner", "owner"),
        repo=config.get("repo", "repo"),
        default_branch=default_branch,
        git_repo=git_repo,
    )
    for prd in config.get("prs", []):
        backend.add_pr(
            title=prd.get("title", "Test PR"),
            head=prd["head"],
            base=prd.get("base"),
            body=prd.get("body", ""),
            is_draft=prd.get("draft", prd.get("is_draft", False)),
            state=prd.get("state", "OPEN"),
            files=prd.get("files"),
        )
    for sd in config.get("scripts", []):
        backend.queue_response(
            sd["match"], returncode=sd.get("returncode", 0),
            stdout=sd.get("stdout", ""), stderr=sd.get("stderr", ""),
            times=sd.get("times", 1))
    save_session(backend, session_tag)
    return backend


def save_session(backend: FakeGitHubBackend,
                 session_tag: Optional[str] = None) -> None:
    """Persist a backend's registry/scripts to the session's state.json."""
    from pm_core import paths
    d = paths.fake_github_dir(session_tag)
    if d is None:
        raise RuntimeError("no pm session tag: cannot save fake-github state")
    d.mkdir(parents=True, exist_ok=True)
    (d / "state.json").write_text(json.dumps(backend.to_state(), indent=2) + "\n")


def load_session(session_tag: Optional[str] = None) -> Optional[FakeGitHubBackend]:
    """Load the session's on-disk fake-github backend, or None if absent."""
    from pm_core import paths
    d = paths.fake_github_dir(session_tag)
    if d is None:
        return None
    state_file = d / "state.json"
    if not state_file.exists():
        return None
    state = json.loads(state_file.read_text())
    git_repo = (FakeGitHubRepo(d / "remote.git", state.get("default_branch", "master"))
                if state.get("git_backed") else None)
    return FakeGitHubBackend.from_state(state, git_repo)


def dispatch_session(args: list[str], cwd: Optional[str] = None,
                     session_tag: Optional[str] = None) -> subprocess.CompletedProcess:
    """Load → run one `gh` command → persist, for the session fake.

    Called by ``gh_ops.run_gh`` when ``paths.fake_github_active()``.
    """
    backend = load_session(session_tag)
    if backend is None:
        return _completed(list(args), 1, "",
                          "fake-gh: no session fake-github installed")
    result = backend.run(list(args), cwd)
    save_session(backend, session_tag)
    return result
