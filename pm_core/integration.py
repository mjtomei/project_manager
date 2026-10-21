"""Integration of a PR with the latest base — the check sign-off runs.

Sign-off owns integration (pr-ac10f03): before it may recommend a merge it
fetches the configured base branch from the target repository and computes
the merge of the PR HEAD with that fetched revision in an **isolated
candidate** — a temporary detached worktree (or, on git >= 2.38, the
in-memory ``git merge-tree --write-tree``).  The PR worktree, its index and
branch, and the shared base are never touched by the check.

The result is recorded twice:

* ``pr["integration"]`` (compact, in project.yaml) — what the sign-off
  verdict and the merge gate bind to: PR HEAD, target repo/branch, fetched
  base revision, candidate tree, status;
* ``$CAP/integration.json`` (full) — conflicting paths, files changed on
  each side and their overlap, for the sign-off agent and whoever the PR is
  routed back to.

Statuses:

* ``up_to_date`` — the fetched base is already in the PR HEAD; the
  candidate is the HEAD's own tree.
* ``clean`` — the base moved and merges without conflicts; the candidate
  tree is the merge result.
* ``conflict`` — merging the base conflicts (``conflicts`` lists paths);
  reconciling is implementation work.
* ``in_base`` — the PR HEAD is already contained in the base (merged).
* ``error`` — the check could not run (no workdir, fetch failed, ...).

:func:`apply_integration` merges a *clean* base into the PR branch; pm uses
it when sign-off routes work back, so the revalidating step sees the
integrated code.  It never leaves a half-merge behind.
"""

from __future__ import annotations

import json
import re
import shutil
import tempfile
from datetime import datetime, timezone
from pathlib import Path

from pm_core import git_ops, store
from pm_core.paths import configure_logger

_log = configure_logger("pm.integration")

UP_TO_DATE = "up_to_date"
CLEAN = "clean"
CONFLICT = "conflict"
IN_BASE = "in_base"
ERROR = "error"

# Statuses whose candidate may be published (conflict-free, not yet merged).
MERGEABLE = (UP_TO_DATE, CLEAN)

# Where the fetched base revision is pinned in the PR workdir, so the
# candidate's objects stay reachable and no shared ref (FETCH_HEAD,
# origin/<base>) an agent may be using is relied on.
BASE_REF = "refs/pm/integration/base"

# Path lists kept in project.yaml are truncated; integration.json has all.
_YAML_LIST_LIMIT = 40

# Keys of an integration record a sign-off verdict binds to.
BINDING_KEYS = ("target_repo", "base_branch", "base_sha", "candidate_tree",
                "status", "head")


def _git(*args: str, cwd) -> "subprocess.CompletedProcess":  # noqa: F821
    return git_ops.run_git(*args, cwd=cwd, check=False)


def _out(r) -> str:
    return (r.stdout or "").strip()


def _detail(r) -> str:
    return ((r.stdout or "") + "\n" + (r.stderr or "")).strip()


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


# --- target + fetch --------------------------------------------------------

def target_for(data: dict, pr: dict, root: Path | None = None) -> tuple[str, str]:
    """``(target_repo, base_branch)`` the PR integrates with and merges into.

    Local backend: the main repo directory (merges land there).  Remote
    backends: the workdir's ``origin`` fetch URL (pushes may fan out to the
    local source as well; publication targets the upstream).
    """
    project = data.get("project") or {}
    base_branch = project.get("base_branch", "master")
    if project.get("backend") == "local":
        from pm_core.cli.helpers import _resolve_repo_dir, state_root
        return str(_resolve_repo_dir(root or state_root(), data)), base_branch
    workdir = pr.get("workdir")
    url = _out(_git("remote", "get-url", "origin", cwd=workdir)) if workdir else ""
    return (url or project.get("repo", "")), base_branch


def fetch_base(workdir: str, target_repo: str, base_branch: str) -> tuple[str | None, str | None]:
    """Fetch *base_branch* from *target_repo* into :data:`BASE_REF`.

    Returns ``(base_sha, None)`` or ``(None, error)``.
    """
    r = _git("fetch", "--no-tags", target_repo,
             f"+refs/heads/{base_branch}:{BASE_REF}", cwd=workdir)
    if r.returncode != 0:
        return None, f"fetch {base_branch} from {target_repo} failed: {_detail(r)}"
    sha = _out(_git("rev-parse", BASE_REF, cwd=workdir))
    return (sha or None), (None if sha else "fetched base has no revision")


def remote_ref(workdir: str, target_repo: str, ref: str) -> str | None:
    """Current revision of *ref* on *target_repo* (``ls-remote``), or None."""
    r = _git("ls-remote", target_repo, ref, cwd=workdir)
    if r.returncode != 0:
        return None
    for line in (r.stdout or "").splitlines():
        parts = line.split()
        if len(parts) == 2 and parts[1] == ref:
            return parts[0]
    return None


# --- candidate -------------------------------------------------------------

def _is_ancestor(cwd, a: str, b: str) -> bool:
    return _git("merge-base", "--is-ancestor", a, b, cwd=cwd).returncode == 0


def _git_version() -> tuple[int, ...]:
    r = git_ops.run_git("--version", check=False)
    m = re.search(r"(\d+)\.(\d+)", r.stdout or "")
    return (int(m.group(1)), int(m.group(2))) if m else (0, 0)


def _merge_tree(workdir: str, head: str, base_sha: str):
    """In-memory merge (git >= 2.38): ``(tree|None, conflicts, error)``."""
    r = _git("merge-tree", "--write-tree", "--name-only", "--no-messages",
             head, base_sha, cwd=workdir)
    lines = (r.stdout or "").splitlines()
    if r.returncode == 0 and lines:
        return lines[0].strip(), [], None
    if r.returncode == 1 and lines:
        return None, sorted({l.strip() for l in lines[1:] if l.strip()}), None
    return None, [], _detail(r) or "git merge-tree failed"


def _worktree_merge(workdir: str, head: str, base_sha: str):
    """Merge in a temporary detached worktree: ``(tree|None, conflicts, error)``."""
    tmp = Path(tempfile.mkdtemp(prefix="pm-integrate-"))
    wt = tmp / "candidate"
    no_hooks = ("-c", "core.hooksPath=/dev/null")
    try:
        add = _git(*no_hooks, "worktree", "add", "--detach", "--quiet",
                   str(wt), head, cwd=workdir)
        if add.returncode != 0:
            return None, [], f"candidate worktree failed: {_detail(add)}"
        m = _git(*no_hooks, "-c", "user.name=pm", "-c", "user.email=pm@localhost",
                 "merge", "--no-commit", "--no-ff", "--no-edit", base_sha, cwd=wt)
        if m.returncode == 0:
            tree = _out(_git("write-tree", cwd=wt))
            return (tree or None), [], (None if tree else "write-tree failed")
        conflicts = _out(_git("diff", "--name-only", "--diff-filter=U", cwd=wt))
        if conflicts:
            return None, sorted(conflicts.splitlines()), None
        return None, [], f"candidate merge failed: {_detail(m)}"
    finally:
        _git("worktree", "remove", "--force", str(wt), cwd=workdir)
        shutil.rmtree(tmp, ignore_errors=True)
        _git("worktree", "prune", cwd=workdir)


def compute_candidate(workdir: str, head: str, base_sha: str) -> dict:
    """Integration of *head* with *base_sha*, without touching the worktree.

    Returns ``{status, candidate_tree, conflicts, merge_base, base_files,
    pr_files, overlap, error?}``.
    """
    out: dict = {"conflicts": [], "base_files": [], "pr_files": [],
                 "overlap": [], "candidate_tree": None}
    mb = _out(_git("merge-base", head, base_sha, cwd=workdir))
    out["merge_base"] = mb or None
    if mb:
        base_files = _out(_git("diff", "--name-only", mb, base_sha, cwd=workdir))
        pr_files = _out(_git("diff", "--name-only", mb, head, cwd=workdir))
        out["base_files"] = base_files.splitlines() if base_files else []
        out["pr_files"] = pr_files.splitlines() if pr_files else []
        out["overlap"] = sorted(set(out["base_files"]) & set(out["pr_files"]))

    if _is_ancestor(workdir, base_sha, head):
        out["status"] = UP_TO_DATE
        out["candidate_tree"] = _out(_git("rev-parse", f"{head}^{{tree}}",
                                          cwd=workdir)) or None
        return out
    if _is_ancestor(workdir, head, base_sha):
        out["status"] = IN_BASE
        return out

    if _git_version() >= (2, 38):
        tree, conflicts, err = _merge_tree(workdir, head, base_sha)
    else:
        tree, conflicts, err = _worktree_merge(workdir, head, base_sha)
    if err:
        out.update(status=ERROR, error=err)
    elif conflicts:
        out.update(status=CONFLICT, conflicts=conflicts)
    else:
        out.update(status=CLEAN, candidate_tree=tree)
    return out


# --- check + record --------------------------------------------------------

def run_check(data: dict, pr: dict, root: Path | None = None) -> dict:
    """Fetch the base and compute the candidate for *pr* (no state writes)."""
    record: dict = {"checked_at": _now()}
    workdir = pr.get("workdir")
    try:
        target_repo, base_branch = target_for(data, pr, root)
    except Exception as e:  # repo dir resolution is best-effort
        target_repo, base_branch = "", (data.get("project") or {}).get(
            "base_branch", "master")
        _log.warning("integration target for %s: %s", pr.get("id"), e)
    record.update(target_repo=target_repo, base_branch=base_branch)
    if not workdir or not Path(workdir).is_dir():
        record.update(status=ERROR, error="no PR workdir")
        return record
    head = _out(_git("rev-parse", "HEAD", cwd=workdir))
    record["head"] = head or None
    if not head:
        record.update(status=ERROR, error="PR workdir has no HEAD")
        return record
    if not target_repo:
        record.update(status=ERROR, error="no target repository")
        return record
    base_sha, err = fetch_base(workdir, target_repo, base_branch)
    record["base_sha"] = base_sha
    if err:
        record.update(status=ERROR, error=err)
        return record
    record.update(compute_candidate(workdir, head, base_sha))
    return record


def compact(record: dict) -> dict:
    """The project.yaml form of an integration record (lists truncated)."""
    out = {k: v for k, v in record.items()
           if k not in ("base_files", "pr_files")}
    for k in ("conflicts", "overlap"):
        vals = list(record.get(k) or [])
        out[k] = vals[:_YAML_LIST_LIMIT]
        if len(vals) > _YAML_LIST_LIMIT:
            out[f"{k}_total"] = len(vals)
    out["base_files_count"] = len(record.get("base_files") or [])
    return out


def integration_json_path(pr_id: str) -> Path | None:
    from pm_core.paths import captures_root
    croot = captures_root()
    return croot / pr_id / "integration.json" if croot else None


def check_integration(root: Path, pr_id: str, *, data: dict | None = None) -> dict:
    """Run the integration check for *pr_id* and record it.

    Writes ``pr["integration"]`` (compact) and ``$CAP/integration.json``
    (full).  Never raises for git/network problems: they come back as
    ``status: error``.
    """
    if data is None:
        data = store.load(root)
    pr = store.get_pr(data, pr_id)
    if pr is None:
        raise ValueError(f"PR {pr_id} not found")
    record = run_check(data, pr, root)
    _log.info("integration %s: %s base=%s head=%s", pr_id, record.get("status"),
              (record.get("base_sha") or "")[:8], (record.get("head") or "")[:8])

    def _apply(d):
        p = store.get_pr(d, pr_id)
        if p is not None:
            p["integration"] = compact(record)

    store.locked_update(root, _apply)
    path = integration_json_path(pr_id)
    if path is not None:
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(json.dumps(record, indent=2) + "\n")
        except OSError as e:
            _log.warning("integration.json for %s: %s", pr_id, e)
    return record


def binding(record: dict | None) -> dict | None:
    """The part of an integration record a sign-off verdict is bound to."""
    if not record:
        return None
    return {k: record.get(k) for k in BINDING_KEYS}


def valid_for(record: dict | None, head: str | None) -> bool:
    """Whether *record* is a mergeable integration check of *head*."""
    return bool(record and head and record.get("head") == head
                and record.get("status") in MERGEABLE
                and record.get("base_sha") and record.get("candidate_tree"))


def summary(record: dict) -> str:
    """One-line human summary of an integration record."""
    status = record.get("status")
    base = f"{record.get('base_branch')}@{(record.get('base_sha') or '?')[:8]}"
    if status == UP_TO_DATE:
        return f"up to date with {base}"
    if status == CLEAN:
        n = len(record.get("overlap") or [])
        return (f"merges cleanly with {base}"
                + (f" ({n} file(s) changed on both sides)" if n else ""))
    if status == CONFLICT:
        files = record.get("conflicts") or []
        return (f"CONFLICTS with {base}: {', '.join(files[:5])}"
                + (" ..." if len(files) > 5 else ""))
    if status == IN_BASE:
        return f"already contained in {base}"
    return f"integration check failed: {record.get('error') or 'unknown error'}"


# --- apply (PR branch only) -----------------------------------------------

def apply_integration(root: Path, pr_id: str, record: dict | None = None,
                      *, data: dict | None = None) -> tuple[str | None, str | None]:
    """Merge the recorded clean base revision into the PR branch.

    Only for a ``clean`` record of the workdir's current HEAD, on the PR
    branch, with a clean tree and no merge in progress.  Returns
    ``(merge_sha, None)`` or ``(None, reason)``; a failed merge is aborted
    so no half-merge is left.  Never touches the base branch and never
    pushes (the merge step pushes the approved PR head where needed).
    """
    if data is None:
        data = store.load(root)
    pr = store.get_pr(data, pr_id) or {}
    if record is None:
        record = pr.get("integration") or {}
    if record.get("status") != CLEAN:
        return None, f"integration is {record.get('status')}, not clean"
    workdir = pr.get("workdir")
    if not workdir or not Path(workdir).is_dir():
        return None, "no PR workdir"
    head = _out(_git("rev-parse", "HEAD", cwd=workdir))
    if head != record.get("head"):
        return None, "PR HEAD moved since the integration check"
    branch = pr.get("branch") or ""
    cur = _out(_git("rev-parse", "--abbrev-ref", "HEAD", cwd=workdir))
    if branch and cur != branch:
        return None, f"workdir is on {cur!r}, not the PR branch {branch!r}"
    if _git("rev-parse", "-q", "--verify", "MERGE_HEAD",
            cwd=workdir).returncode == 0:
        return None, "a merge is already in progress in the workdir"
    if _out(_git("status", "--porcelain", "--untracked-files=no", cwd=workdir)):
        return None, "workdir has uncommitted changes"
    base_sha = record.get("base_sha")
    msg = (f"Integrate {record.get('base_branch')}@{base_sha[:8]} into "
           f"{branch or 'PR branch'}")
    m = _git("merge", "--no-ff", "-m", msg, base_sha, cwd=workdir)
    if m.returncode != 0:
        _git("merge", "--abort", cwd=workdir)
        return None, f"merge failed: {_detail(m)}"
    merged = _out(_git("rev-parse", "HEAD", cwd=workdir))
    tree = _out(_git("rev-parse", "HEAD^{tree}", cwd=workdir))
    if record.get("candidate_tree") and tree != record["candidate_tree"]:
        _log.warning("integration apply %s: tree %s != candidate %s",
                     pr_id, tree[:8], record["candidate_tree"][:8])
    return merged or None, None


# --- publication helpers (used by `pm pr merge`) --------------------------

def build_merge_commit(workdir: str, tree: str, base_sha: str, head: str,
                       message: str) -> tuple[str | None, str | None]:
    """``git commit-tree`` the approved candidate: parents (base, head)."""
    r = _git("commit-tree", tree, "-p", base_sha, "-p", head, "-m", message,
             cwd=workdir)
    sha = _out(r)
    if r.returncode != 0 or not sha:
        return None, f"commit-tree failed: {_detail(r)}"
    return sha, None
