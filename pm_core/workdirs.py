"""Locate a PR's workdir, recovering a stale record from the filesystem.

A PR's ``workdir`` field in project.yaml is a machine-local absolute path.
It goes stale when the PR was started under another HOME or machine, or the
record was rewritten, while the clone itself — PR branch, uncommitted work,
stashes, evidence — is still sitting in this machine's project workdirs
directory.  Treating that as "no workdir" made pm clone a second one.

:func:`resolve_workdir` keeps the fast path (a recorded path that exists is
returned as-is: no git, no listing, no lock) and only when the record is
missing or points nowhere looks in **one** directory — this project's
workdirs dir — for a clone named after the PR's branch slug, verifies it
read-only (own repository, this project's repository, checked out on the PR
branch), and re-links it.  Two verified clones are reported, never resolved
by picking one.  Nothing here runs on registry load; callers invoke it when
a specific PR's workdir is actually needed.
"""

from __future__ import annotations

import contextlib
import fcntl
import os
import re
import subprocess
from dataclasses import dataclass, field
from pathlib import Path

from pm_core import store
from pm_core.paths import configure_logger

_log = configure_logger("pm.workdirs")

RECORDED = "recorded"
RECOVERED = "recovered"
AMBIGUOUS = "ambiguous"
MISSING = "missing"

# More name matches than this is not a recoverable layout; report it instead
# of running git in every one of them.
MAX_CANDIDATES = 16
_GIT_TIMEOUT = 15.0
# Variables that make git operate on a repository other than the one at its
# cwd (set e.g. when pm runs from a git hook).  Inherited, they would make
# every candidate "verify" as that repository.
_GIT_LOCATION_VARS = ("GIT_DIR", "GIT_WORK_TREE", "GIT_COMMON_DIR",
                      "GIT_INDEX_FILE", "GIT_OBJECT_DIRECTORY",
                      "GIT_ALTERNATE_OBJECT_DIRECTORIES", "GIT_NAMESPACE",
                      "GIT_CEILING_DIRECTORIES")
# ``<branch_slug>`` or ``<branch_slug>-<base hash>`` (``rev-parse --short=8``
# may lengthen the hash when it is ambiguous; :func:`clone_destination` falls
# back to the full SHA-1/SHA-256 hash).
_HASH_SUFFIX = r"(?:-[0-9a-f]{7,64})?"


@dataclass
class WorkdirResolution:
    """Outcome of :func:`resolve_workdir`."""

    pr_id: str | None
    status: str
    path: str | None = None
    recorded: str | None = None
    branch: str | None = None
    project_dir: str | None = None
    candidates: list[str] = field(default_factory=list)
    rejected: list[tuple[str, str]] = field(default_factory=list)
    # AMBIGUOUS because of too many name matches: *candidates* were never
    # verified, only matched by name.
    unverified: bool = False

    @property
    def reportable(self) -> bool:
        """Whether callers should show :meth:`describe`: a re-link, an
        ambiguity, or same-named clones that were skipped (so a fresh clone
        made next to them is explained)."""
        return self.status in (RECOVERED, AMBIGUOUS) or bool(self.rejected)

    def describe(self) -> str:
        """User-facing account of the outcome."""
        where = (f"recorded path {self.recorded} is missing"
                 if self.recorded else "no workdir is recorded")
        if self.status == RECORDED:
            return f"Workdir for {self.pr_id}: {self.path}"
        if self.status == RECOVERED:
            return (f"Workdir for {self.pr_id}: {where}; re-linked the "
                    f"existing clone on {self.branch} at {self.path}")
        if self.status == AMBIGUOUS and self.unverified:
            lines = [f"Workdir for {self.pr_id}: {where} and "
                     f"{len(self.candidates)} directories in "
                     f"{self.project_dir} are named after branch "
                     f"{self.branch} (more than {MAX_CANDIDATES}; none "
                     "verified):"]
            lines += [f"  - {c}" for c in self.candidates]
            lines.append("Not choosing one. Move the clones that aren't "
                         "this PR's out of that directory; the next use of "
                         "this PR's workdir verifies the rest.")
            return "\n".join(lines)
        if self.status == AMBIGUOUS:
            lines = [f"Workdir for {self.pr_id}: {where} and "
                     f"{len(self.candidates)} existing clones in "
                     f"{self.project_dir} match branch {self.branch}:"]
            lines += [f"  - {c}" for c in self.candidates]
            lines.append(
                "Not choosing one. Move the extra clone(s) out of that "
                "directory (or check out another branch in them); the next "
                "use of this PR's workdir re-links the one that remains.")
            return "\n".join(lines)
        lines = [f"Workdir for {self.pr_id}: {where} and no existing clone "
                 f"of branch {self.branch} was found"
                 + (f" in {self.project_dir}" if self.project_dir else "")]
        lines += [f"  - skipped {p}: {why}" for p, why in self.rejected]
        return "\n".join(lines)


def branch_slug(branch: str) -> str:
    """*branch* as a directory-name slug (``pm/pr-x-title`` → ``pm-pr-x-title``,
    truncated by :func:`pm_core.store.slugify`)."""
    return store.slugify(branch.replace("/", "-"))


def workdir_name(branch: str, base_hash: str = "") -> str:
    """The directory name a PR's clone gets: ``<branch_slug>-<base_hash>``,
    or the bare slug without a hash.

    ``pm pr start`` and ``_clone_workdir`` name clones with this (through
    :func:`clone_destination`), and :func:`resolve_workdir` finds them by
    it, so the two cannot drift apart.
    """
    slug = branch_slug(branch)
    return f"{slug}-{base_hash}" if base_hash else slug


def project_workdirs_dir(data: dict) -> Path:
    """This project's workdirs directory (not created).

    ``<workdirs_base>/<name>-<repo_id[:8]>`` — the 8-char root-commit prefix
    keeps same-named projects apart — or ``<workdirs_base>/<name>`` before
    the repo id is cached (on first ``pr start``).
    """
    from pm_core.paths import workdirs_base
    project = data.get("project") or {}
    name = project.get("name", "unknown")
    repo_id = project.get("repo_id")
    base = workdirs_base()
    if repo_id:
        return base / f"{name}-{repo_id[:8]}"
    return base / name


@contextlib.contextmanager
def workdir_lock(project_dir: Path, pr_id: str):
    """Hold the per-PR workdir provisioning lock (blocking, exclusive).

    The same ``.workdir-<pr_id>.lock`` that serializes cloning in
    ``_ensure_workdir``, so recovery and cloning never race.  flock is per
    open file description: a caller already holding it must not re-enter
    (pass ``locked=True`` to :func:`resolve_workdir` instead).
    """
    project_dir.mkdir(parents=True, exist_ok=True)
    fd = os.open(str(project_dir / f".workdir-{pr_id}.lock"),
                 os.O_CREAT | os.O_RDWR, 0o644)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX)
        yield
    finally:
        fcntl.flock(fd, fcntl.LOCK_UN)
        os.close(fd)


def _git(cwd: Path, *args: str) -> tuple[int | None, str, str]:
    """Run a read-only git command; ``(returncode, stdout, stderr)``.

    ``GIT_OPTIONAL_LOCKS=0`` keeps git from refreshing (and so locking or
    rewriting) the candidate's index, and the repository-locating variables
    are dropped so git inspects *cwd*, not an inherited ``GIT_DIR``;
    ``returncode`` is None when git could not run or timed out.
    """
    env = {k: v for k, v in os.environ.items()
           if k not in _GIT_LOCATION_VARS}
    env.update(GIT_OPTIONAL_LOCKS="0", GIT_TERMINAL_PROMPT="0")
    try:
        r = subprocess.run(["git", *args], cwd=str(cwd), env=env,
                           capture_output=True, text=True,
                           timeout=_GIT_TIMEOUT)
    except (OSError, subprocess.SubprocessError) as e:
        return None, "", str(e)
    return r.returncode, r.stdout.strip(), r.stderr.strip()


def _same_repo_url(a: str, b: str) -> bool:
    def norm(u: str) -> str:
        u = u.strip().rstrip("/")
        return u[:-4] if u.endswith(".git") else u
    if not a or not b:
        return False
    if norm(a) == norm(b):
        return True
    try:
        pa, pb = Path(a), Path(b)
        return pa.is_dir() and pb.is_dir() and pa.resolve() == pb.resolve()
    except (OSError, ValueError):
        return False


def _checked_out_branch(path: Path) -> tuple[str | None, str]:
    """The branch *path* has checked out, or ``(None, why)``.

    A rebase in progress detaches HEAD; its ``head-name`` names the branch
    being rebased, which is still the workdir's branch.
    """
    rc, out, err = _git(path, "symbolic-ref", "-q", "HEAD")
    if rc == 0 and out.startswith("refs/heads/"):
        return out[len("refs/heads/"):], ""
    rc, gitdir, err = _git(path, "rev-parse", "--absolute-git-dir")
    if rc == 0 and gitdir:
        for state in ("rebase-merge", "rebase-apply"):
            try:
                name = (Path(gitdir) / state / "head-name").read_text().strip()
            except OSError:
                continue
            if name.startswith("refs/heads/"):
                return name[len("refs/heads/"):], ""
    return None, "HEAD is detached"


def verify_candidate(path: Path, data: dict, branch: str) -> str | None:
    """Why *path* is not this PR's workdir, or None when it is.

    Read-only: never touches the candidate's index, worktree, stashes or
    refs.
    """
    rc, top, err = _git(path, "rev-parse", "--show-toplevel")
    if rc != 0 or not top:
        return f"not a git repository ({err.splitlines()[0] if err else 'git failed'})"
    try:
        if Path(top).resolve() != path.resolve():
            return f"not its own repository (inside {top})"
    except OSError as e:
        return f"cannot resolve path ({e})"

    project = data.get("project") or {}
    repo_id = str(project.get("repo_id") or "")
    if re.fullmatch(r"[0-9a-f]{7,64}", repo_id):
        rc, _, _ = _git(path, "cat-file", "-e", f"{repo_id}^{{commit}}")
        if rc != 0:
            return f"different repository (root commit {repo_id[:8]} absent)"
    elif project.get("repo"):
        rc, origin, _ = _git(path, "config", "--get", "remote.origin.url")
        if not _same_repo_url(origin, project["repo"]):
            return f"different repository (origin {origin or 'unset'})"
    else:
        return "repository identity unverifiable (no repo_id or repo URL)"

    current, why = _checked_out_branch(path)
    if current is None:
        return why
    if current != branch:
        return f"on branch {current}, not {branch}"
    return None


def clone_destination(data: dict, project_dir: Path, branch: str,
                      base_hash: str, clone: Path) -> Path | None:
    """Where a fresh clone of *branch*, still at its temporary path *clone*,
    is moved to; None when there is nowhere safe.

    Normally ``project_dir / workdir_name(branch, base_hash)``.  A directory
    already at that name is returned only when it verifies as this PR's
    clone (a concurrent start got there first; callers discard *clone* and
    use it).  Any other occupant — a clone on another branch or detached, a
    different repository, a plain directory — is one discovery did not
    adopt: taking it over would check the PR branch out over its work.  The
    clone then gets the full base hash, a name discovery still matches.
    """
    dest = project_dir / workdir_name(branch, base_hash)
    if not os.path.lexists(dest):
        return dest
    why = verify_candidate(dest, data, branch)
    if why is None:
        return dest
    rc, full, _ = _git(clone, "rev-parse", "HEAD")
    if rc == 0 and full and full != base_hash:
        alt = project_dir / workdir_name(branch, full)
        if not os.path.lexists(alt):
            _log.info("new clone of %s goes to %s: %s is taken (%s)",
                      branch, alt, dest, why)
            return alt
    _log.warning("no free workdir name for %s in %s: %s is taken (%s)",
                 branch, project_dir, dest, why)
    return None


def _name_matches(project_dir: Path, branch: str) -> list[Path]:
    """Directories in *project_dir* named after *branch* (one level only).

    Entries that resolve to the same directory count once; the real
    directory is kept over a symlink alias, so that is the path recorded.
    """
    slug = branch_slug(branch)
    if not slug:
        return []
    pattern = re.compile(re.escape(slug) + _HASH_SUFFIX)
    try:
        entries = list(os.scandir(project_dir))
    except OSError:
        return []
    by_real: dict[str, tuple[bool, str]] = {}
    for entry in sorted(entries, key=lambda e: e.name):
        if entry.name.startswith(".") or not pattern.fullmatch(entry.name):
            continue
        try:
            if not entry.is_dir():
                continue
            alias = entry.is_symlink()
        except OSError:
            continue
        real = os.path.realpath(entry.path)
        if real not in by_real or (by_real[real][0] and not alias):
            by_real[real] = (alias, entry.path)
    return sorted(Path(p) for _, p in by_real.values())


def resolve_workdir(data: dict, pr_entry: dict, root: Path | None = None, *,
                    project_dir: Path | None = None, persist: bool = True,
                    locked: bool = False) -> WorkdirResolution:
    """Resolve *pr_entry*'s workdir, recovering it when the record is stale.

    A recorded path that exists is returned directly.  Otherwise the PR's
    branch-slug-named clones in this project's workdirs dir are verified
    (:func:`verify_candidate`); exactly one verified clone is adopted —
    ``pr_entry["workdir"]`` is updated and, with *root* and *persist*, the
    record is compare-and-set in project.yaml.  Several verified clones are
    ``AMBIGUOUS`` (nothing adopted or written; do not clone another).

    *project_dir* overrides :func:`project_workdirs_dir`.  *locked* says the
    caller already holds :func:`workdir_lock` for this PR.
    """
    pr_id = pr_entry.get("id")
    recorded = pr_entry.get("workdir") or None
    if recorded and Path(recorded).exists():
        return WorkdirResolution(pr_id, RECORDED, path=recorded,
                                 recorded=recorded)

    branch = pr_entry.get("branch") or None
    if project_dir is None:
        project_dir = project_workdirs_dir(data)
    res = WorkdirResolution(pr_id, MISSING, recorded=recorded, branch=branch,
                            project_dir=str(project_dir))
    if not branch or not pr_id or not _name_matches(project_dir, branch):
        return res

    if locked:
        return _resolve_matches(data, pr_entry, root, res, persist,
                                reread=False)
    with workdir_lock(project_dir, pr_id):
        return _resolve_matches(data, pr_entry, root, res, persist,
                                reread=True)


def _resolve_matches(data: dict, pr_entry: dict, root: Path | None,
                     res: WorkdirResolution, persist: bool,
                     reread: bool) -> WorkdirResolution:
    """Verify name matches and adopt a unique one.  Caller holds the lock."""
    pr_id, branch, recorded = res.pr_id, res.branch, res.recorded
    if reread and root is not None:
        # Double-checked: a concurrent caller may have re-linked or cloned
        # and persisted while we waited for the lock.
        fresh = stored_workdir(root, pr_id)
        if fresh and Path(fresh).exists():
            pr_entry["workdir"] = fresh
            res.status, res.path = RECORDED, fresh
            return res

    matches = _name_matches(Path(res.project_dir), branch)
    if len(matches) > MAX_CANDIDATES:
        res.status, res.unverified = AMBIGUOUS, True
        res.candidates = [str(p) for p in matches]
        _log.warning("workdir for %s: %d name matches in %s, not verifying",
                     pr_id, len(matches), res.project_dir)
        return res
    for cand in matches:
        why = verify_candidate(cand, data, branch)
        if why:
            res.rejected.append((str(cand), why))
        else:
            res.candidates.append(str(cand))
    for p, why in res.rejected:
        _log.info("workdir for %s: skipped %s: %s", pr_id, p, why)

    if len(res.candidates) > 1:
        res.status = AMBIGUOUS
        _log.warning("workdir for %s: %d verified clones, not choosing: %s",
                     pr_id, len(res.candidates), ", ".join(res.candidates))
        return res
    if not res.candidates:
        return res

    found = res.candidates[0]
    if persist and root is not None:
        found = _persist(root, pr_id, found)
    pr_entry["workdir"] = found
    res.path = found
    res.status = RECOVERED if found == res.candidates[0] else RECORDED
    _log.info("workdir for %s: recorded %s missing; re-linked %s",
              pr_id, recorded, found)
    return res


def stored_workdir(root: Path, pr_id: str) -> str | None:
    """The workdir currently recorded on disk for *pr_id* (re-read, not the
    caller's in-memory copy); None when unset or project.yaml can't be read.
    The double-check after taking :func:`workdir_lock`."""
    try:
        pr = store.get_pr(store.load(root), pr_id)
    except Exception:
        return None
    return (pr or {}).get("workdir") or None


def _persist(root: Path, pr_id: str, found: str) -> str:
    """Compare-and-set the recovered path; return the path now in effect.

    Written only while the on-disk record is still empty or still points at
    a missing path; a record that exists by now — another writer's, or the
    stale path itself reappearing (a remount) — wins and is returned instead.
    """
    winner = found

    def apply(fresh_data):
        nonlocal winner
        pr = store.get_pr(fresh_data, pr_id)
        if pr is None:
            return
        cur = pr.get("workdir")
        if cur and Path(cur).exists():
            winner = cur
            return
        pr["workdir"] = found

    try:
        store.locked_update(root, apply)
    except Exception as e:  # the in-memory adoption still stands
        _log.warning("workdir for %s: could not record %s: %s",
                     pr_id, found, e)
    return winner


def get_workdir(data: dict, pr_entry: dict, root: Path | None = None,
                **kwargs) -> str | None:
    """The PR's workdir path, recovered from the filesystem when stale.

    None when there is no workdir or the recovery is ambiguous; use
    :func:`resolve_workdir` to tell those apart.
    """
    return resolve_workdir(data, pr_entry, root, **kwargs).path
