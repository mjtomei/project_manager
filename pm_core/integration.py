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
* ``resolved`` — the merge conflicted only in ``project.yaml`` file(s) and
  pm's record-aware resolver combined both sides safely; the candidate tree
  is the conflict-free merge with the resolved documents.  ``resolution``
  records exactly what was combined (see :func:`resolve_project_yaml`).
* ``conflict`` — merging the base conflicts (``conflicts`` lists paths);
  reconciling is implementation work.  ``resolution`` carries a failed
  attempt's details when the conflict was metadata-only.
* ``in_base`` — the PR HEAD is already contained in the base (merged).
* ``error`` — the check could not run (no workdir, fetch failed, ...).

:func:`apply_integration` merges a *clean* base into the PR branch (or
applies a *resolved* candidate's resolution and verifies the resulting tree
matches the candidate); pm uses it when sign-off routes work back, so the
revalidating step sees the integrated code.  It never leaves a half-merge
behind.  :func:`prepare` is what a sign-off launch runs: check, apply a
resolved candidate, re-check, and record the resolution provenance.
"""

from __future__ import annotations

import contextlib
import difflib
import functools
import hashlib
import io
import json
import os
import re
import secrets
import shutil
import stat
import subprocess
import tempfile
from datetime import datetime, timezone
from pathlib import Path

import yaml

from pm_core import git_ops, store
from pm_core.paths import configure_logger

_log = configure_logger("pm.integration")

UP_TO_DATE = "up_to_date"
CLEAN = "clean"
RESOLVED = "resolved"
CONFLICT = "conflict"
IN_BASE = "in_base"
ERROR = "error"

# Statuses whose candidate may be published (conflict-free, not yet merged).
MERGEABLE = (UP_TO_DATE, CLEAN, RESOLVED)

# A concurrent actor moved the PR HEAD between the check and the apply (two
# operators running ``--apply`` at once).  Named so the caller can tell this
# lost race from a workdir that genuinely cannot take the merge.
HEAD_MOVED = "PR HEAD moved since the integration check"
HEAD_MOVED_APPLYING = "PR HEAD moved while applying the resolution"

# Where the fetched base revision is pinned in the PR workdir, so the
# candidate's objects stay reachable and no shared ref (FETCH_HEAD,
# origin/<base>) an agent may be using is relied on.
BASE_REF = "refs/pm/integration/base"

# Path lists kept in project.yaml are truncated; integration.json has all.
_YAML_LIST_LIMIT = 40

# Keys of an integration record a sign-off verdict binds to.
BINDING_KEYS = ("target_repo", "base_branch", "base_sha", "candidate_tree",
                "status", "head", "resolution_digest")

# Bounds for state / artifacts.  project.yaml keeps summaries; the full
# resolution (and its diff) lives in $CAP/<pr>/integration.json.
_BEHAVIOR_LIMIT = 30
_DIFF_LINE_LIMIT = 1500


def _git(*args: str, cwd) -> subprocess.CompletedProcess:
    return git_ops.run_git(*args, cwd=cwd, check=False)


def _out(r) -> str:
    return (r.stdout or "").strip()


def _detail(r) -> str:
    return ((r.stdout or "") + "\n" + (r.stderr or "")).strip()


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


# Bounded so a hung holder (e.g. a stalled fetch) delays a check, not wedges it.
_REPO_LOCK_TIMEOUT = 300.0


@contextlib.contextmanager
def _repo_lock(workdir: str):
    """Serialize pm's fetches and candidate worktrees in one repository.

    On git < 2.38 each check adds and removes a worktree in the shared
    repository; a concurrent ``git fetch`` there walks every worktree's HEAD
    and fails on a half-created one ("bad object worktrees/<name>/HEAD"),
    and concurrent ``worktree add`` calls collide on admin dir names.
    """
    common = _out(_git("rev-parse", "--git-common-dir", cwd=workdir))
    if not common:
        yield
        return
    path = Path(workdir, common) / "pm-integration.lock"
    with contextlib.ExitStack() as stack:
        try:
            held = stack.enter_context(
                store.bounded_flock(path, _REPO_LOCK_TIMEOUT))
        except OSError:
            held = None  # no lock file (e.g. read-only repo): unserialized
        if held is False:
            _log.warning("integration lock %s busy; proceeding", path)
        yield


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
        from pm_core.paths import workdirs_base
        repo_dir = _resolve_repo_dir(root or state_root(), data)
        # Run from a PR workdir (a pm clone of the main repo), the clone's
        # own base branch is stale: the main repo is the clone's origin.
        # An unreachable origin stays the target so the fetch fails loudly
        # instead of checking against the clone's own stale branch.
        try:
            in_workdirs = repo_dir.resolve().is_relative_to(
                workdirs_base().resolve())
        except OSError:
            in_workdirs = False
        if in_workdirs:
            origin = _out(_git("remote", "get-url", "origin", cwd=repo_dir))
            return origin, base_branch
        return str(repo_dir), base_branch
    workdir = pr.get("workdir")
    url = (_out(_git("remote", "get-url", "origin", cwd=workdir))
           if workdir and Path(workdir).is_dir() else "")
    return (url or project.get("repo", "")), base_branch


def same_target(a: str, b: str) -> bool:
    """Whether two target repositories name the same repository.

    Local paths compare resolved (a PR workdir's origin and the main repo
    dir can spell one directory differently); URLs compare verbatim.
    """
    if a == b:
        return True
    try:
        pa, pb = Path(a), Path(b)
        return pa.is_dir() and pb.is_dir() and pa.resolve() == pb.resolve()
    except (OSError, ValueError):
        return False


def fetch_base(workdir: str, target_repo: str, base_branch: str) -> tuple[str | None, str | None]:
    """Fetch *base_branch* from *target_repo* into :data:`BASE_REF`.

    Returns ``(base_sha, None)`` or ``(None, error)``.
    """
    # Each call fetches into its own ref: concurrent checks on one workdir
    # would otherwise race on the fetch's compare-and-swap of BASE_REF
    # ("cannot lock ref") or read each other's revision.
    own_ref = f"{BASE_REF}-{os.getpid()}-{secrets.token_hex(4)}"
    with _repo_lock(workdir):
        return _fetch_into(workdir, target_repo, base_branch, own_ref)


def _fetch_into(workdir: str, target_repo: str, base_branch: str,
                own_ref: str) -> tuple[str | None, str | None]:
    sha = None
    try:
        r = _git("fetch", "--no-tags", target_repo,
                 f"+refs/heads/{base_branch}:{own_ref}", cwd=workdir)
        if r.returncode != 0:
            return None, f"fetch {base_branch} from {target_repo} failed: {_detail(r)}"
        sha = _out(_git("rev-parse", own_ref, cwd=workdir))
        if sha:
            # Unconditional update (no expected old value; git retries the
            # lock), so a concurrent pin cannot fail the check.
            _git("update-ref", BASE_REF, sha, cwd=workdir)
    finally:
        _git("update-ref", "-d", own_ref, cwd=workdir)
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


# --- structured project.yaml resolution ------------------------------------
# Git reports a conflict for two branches that independently appended records
# to project.yaml, but the documents are mergeable by record id.  This
# resolver is deliberately *not* ``store.merge_3way``: that policy lets the
# live state win true conflicts, which is right for pm's own stash-pop but
# wrong for an integration candidate that a human will approve.  Here a real
# field conflict, a deletion/edit conflict or an ambiguous record is a
# conflict — never a silent side selection.

_MISSING = object()
_DELETED = object()

# Bookkeeping timestamps are bumped independently whenever either side touches
# a record: ``pm pr note add`` and every status change call
# ``_record_status_timestamp``, which rewrites ``updated_at`` (and the
# transition stamp).  Two branches that both edited the same record therefore
# change ``updated_at`` to different values even when the records themselves
# are independently mergeable — the real #250 note-add path does exactly this.
# These are not semantic fields: take the later value ("last touched") instead
# of failing the whole metadata resolution, and do not count the earlier value
# as a lost change.  Anything that is not a string timestamp keeps the normal
# conflict rule.
_BOOKKEEPING_TS = frozenset({
    "created_at", "updated_at", "last_edited", "started_at", "reviewed_at",
    "signed_off_at", "merged_at",
})


def _bookkeeping_ts(path: str) -> bool:
    return path.rsplit(".", 1)[-1] in _BOOKKEEPING_TS


def _merge_bookkeeping_ts(ours, theirs):
    """The merged value of a bookkeeping timestamp, or ``_MISSING``."""
    if not all(v is None or isinstance(v, str) for v in (ours, theirs)):
        return _MISSING
    if ours is None:
        return theirs
    if theirs is None:
        return ours
    return max(ours, theirs)      # ISO-8601 strings sort chronologically


def resolve_project_yaml(base_text: str | None, ours_text: str | None,
                         theirs_text: str | None):
    """Merge three versions of a project.yaml document by record id.

    *base_text* is the merge-base version (``None`` when the file did not
    exist there), *ours_text* the PR branch's version and *theirs_text* the
    new base's version.  Returns ``(merged_text, details)``; on any real
    conflict, ambiguity or failed validation returns ``(None, details)``
    with a human-readable ``conflicts`` list.  ``details["actions"]`` names
    the record ids added/removed/changed per list path.
    """
    try:
        base = _parse_yaml(base_text)
        ours = _parse_yaml(ours_text)
        theirs = _parse_yaml(theirs_text)
    except (yaml.YAMLError, ValueError) as e:
        return None, {"error": f"cannot parse project.yaml: {e}"}
    if not isinstance(ours, dict) or not isinstance(theirs, dict):
        return None, {"error": "project.yaml is not a mapping on one side"}
    if base is not _MISSING and not isinstance(base, dict):
        return None, {"error": "project.yaml base is not a mapping"}
    ambiguous = (_duplicate_id_problems(ours, "PR branch")
                 + _duplicate_id_problems(theirs, "new base")
                 + (_duplicate_id_problems(base, "merge base")
                    if base is not _MISSING else []))
    if ambiguous:
        return None, {"conflicts": ambiguous}

    actions: dict = {}
    merged, conflicts = _merge_value(base, ours, theirs, "", actions)
    if conflicts:
        return None, {"conflicts": conflicts, "actions": actions}
    problems = (_preservation_problems(base, ours, merged, "PR branch")
                + _preservation_problems(base, theirs, merged, "new base"))
    problems += _shape_problems(merged)
    if problems:
        return None, {"conflicts": problems, "actions": actions}
    try:
        return _dump_project_yaml(merged), {"actions": actions}
    except (yaml.YAMLError, ValueError) as e:
        return None, {"error": f"cannot serialize project.yaml: {e}"}


def _yaml_load(text: str):
    """Parse YAML with the store's loader (C-accelerated when available).

    project.yaml is large enough that the pure-Python loader dominates a
    sign-off's resolution time; this is the same loader ``store`` uses.
    """
    return yaml.load(text, Loader=store._yaml_loader())


def _parse_yaml(text: str | None):
    if text is None:
        return _MISSING
    if not text.strip():
        return {}
    return _yaml_load(text)


def _dump_project_yaml(data: dict) -> str:
    """Serialize exactly like :func:`pm_core.store.save` (byte-stable)."""
    buf = io.StringIO()
    buf.write(store._YAML_HEADER)
    yaml.dump(data, buf, Dumper=store._yaml_dumper(data),
              default_flow_style=False, sort_keys=False, allow_unicode=True)
    return buf.getvalue()


def _is_id_list(value) -> bool:
    # The id must be a string: ids are used as dict keys (a mapping/list id
    # is unhashable) and pm's own records always use string ids.  A list
    # with any other id type is treated as an atomic value, so a malformed
    # record becomes a conflict instead of an exception.
    return isinstance(value, list) and all(
        isinstance(e, dict) and isinstance(e.get("id"), str) for e in value)


def _duplicate_id_problems(data, label: str) -> list[str]:
    """A document whose id-keyed list repeats an id is ambiguous."""
    if not isinstance(data, dict):
        return []
    problems: list[str] = []
    for path, value in data.items():
        if not _is_id_list(value):
            continue
        seen: set = set()
        for entry in value:
            rec_id = entry["id"]
            if rec_id in seen:
                problems.append(
                    f"{path}: duplicate record id {rec_id!r} on the {label} "
                    "side (ambiguous)")
            seen.add(rec_id)
    return problems


def _record_action(actions: dict, path: str, kind: str,
                   side: str | None = None, rec_id: str | None = None) -> None:
    entry = actions.setdefault(
        path or "<root>",
        {"added": {"PR branch": [], "new base": []}, "removed": [],
         "changed": []})
    if kind == "added":
        entry["added"].setdefault(side, []).append(rec_id)
    elif kind == "removed":
        entry["removed"].append(rec_id)
    elif kind == "changed":
        entry["changed"].append(rec_id)


def _merge_value(base, ours, theirs, path: str, actions: dict):
    """``(value, conflicts)`` for one position in the document tree."""
    if ours == theirs:
        return ours, []
    if base is not _MISSING and ours == base:
        return theirs, []
    if base is not _MISSING and theirs == base:
        return ours, []
    if isinstance(ours, dict) and isinstance(theirs, dict):
        if base is _MISSING:
            return None, [f"{path or '<root>'}: added on both sides with "
                          "different content"]
        if not isinstance(base, dict):
            return None, [f"{path or '<root>'}: type conflict"]
        return _merge_dict(base, ours, theirs, path, actions)
    if _is_id_list(ours) and _is_id_list(theirs) \
            and (base is _MISSING or _is_id_list(base)):
        # A list absent in the merge base (e.g. a PR record that had no
        # ``notes`` key) merges like an empty one: independent additions
        # survive and a same-id/different-content entry is still ambiguous.
        # The preservation check below proves neither side lost an entry.
        return _merge_id_list([] if base is _MISSING else base, ours, theirs,
                              path, actions)
    if _bookkeeping_ts(path):
        value = _merge_bookkeeping_ts(ours, theirs)
        if value is not _MISSING:
            return value, []
    return None, [f"{path or '<root>'}: changed differently on both sides"]


def _merge_dict(base: dict, ours: dict, theirs: dict, path: str, actions: dict):
    out: dict = {}
    conflicts: list[str] = []
    keys: list = list(base)
    keys += [k for k in ours if k not in keys]
    keys += [k for k in theirs if k not in keys]
    for key in keys:
        in_b, in_o, in_t = key in base, key in ours, key in theirs
        key_path = f"{path}.{key}" if path else str(key)
        if in_o and in_t:
            value, problems = _merge_value(
                base[key] if in_b else _MISSING, ours[key], theirs[key],
                key_path, actions)
            if problems:
                conflicts.extend(problems)
            else:
                out[key] = value
        elif in_o:
            if in_b:
                if ours[key] == base[key]:
                    _record_action(actions, path, "removed", rec_id=str(key))
                else:
                    conflicts.append(
                        f"{key_path}: deleted on the new base, changed on the "
                        "PR branch")
            else:
                out[key] = ours[key]           # added by the PR branch
        elif in_t:
            if in_b:
                if theirs[key] == base[key]:
                    _record_action(actions, path, "removed", rec_id=str(key))
                else:
                    conflicts.append(
                        f"{key_path}: deleted on the PR branch, changed on the "
                        "new base")
            else:
                out[key] = theirs[key]         # added by the new base
        # absent from both sides: deleted by both
    return out, conflicts


def _merge_id_list(base: list, ours: list, theirs: list, path: str,
                   actions: dict):
    b = {e["id"]: e for e in base}
    o = {e["id"]: e for e in ours}
    t = {e["id"]: e for e in theirs}
    for label, seq in (("PR branch", [e["id"] for e in ours]),
                       ("new base", [e["id"] for e in theirs]),
                       ("merge base", [e["id"] for e in base])):
        if len(seq) != len(set(seq)):
            return None, [f"{path or '<root>'}: duplicate record id on the "
                          f"{label} side"]

    conflicts: list[str] = []
    results: dict = {}
    for rec_id in list(b) + [i for i in o if i not in b] \
            + [i for i in t if i not in b and i not in o]:
        rec_path = f"{path}[{rec_id}]"
        in_b, in_o, in_t = rec_id in b, rec_id in o, rec_id in t
        if in_o and in_t:
            value, problems = _merge_value(
                b[rec_id] if in_b else _MISSING, o[rec_id], t[rec_id],
                rec_path, actions)
            if problems:
                conflicts.extend(problems)
                continue
            results[rec_id] = value
            if in_b and o[rec_id] != b[rec_id] \
                    and t[rec_id] != b[rec_id] and o[rec_id] != t[rec_id]:
                _record_action(actions, path, "changed", rec_id=rec_id)
            elif not in_b:
                _record_action(actions, path, "added",
                               side="PR branch", rec_id=rec_id)
                _record_action(actions, path, "added",
                               side="new base", rec_id=rec_id)
        elif in_b and in_o:
            if o[rec_id] == b[rec_id]:
                results[rec_id] = _DELETED
                _record_action(actions, path, "removed", rec_id=rec_id)
            else:
                conflicts.append(f"{rec_path}: deleted on the new base, "
                                 "changed on the PR branch")
        elif in_b and in_t:
            if t[rec_id] == b[rec_id]:
                results[rec_id] = _DELETED
                _record_action(actions, path, "removed", rec_id=rec_id)
            else:
                conflicts.append(f"{rec_path}: deleted on the PR branch, "
                                 "changed on the new base")
        elif in_o:
            results[rec_id] = o[rec_id]
            _record_action(actions, path, "added",
                           side="PR branch", rec_id=rec_id)
        elif in_t:
            results[rec_id] = t[rec_id]
            _record_action(actions, path, "added",
                           side="new base", rec_id=rec_id)
        else:
            results[rec_id] = _DELETED         # deleted by both

    if conflicts:
        return None, conflicts

    base_seq = [e["id"] for e in base]
    ours_seq = [e["id"] for e in ours]
    theirs_seq = [e["id"] for e in theirs]
    common = [i for i in base_seq if i in o and i in t]
    o_order = [i for i in ours_seq if i in common]
    t_order = [i for i in theirs_seq if i in common]
    if o_order != common and t_order != common and o_order != t_order:
        return None, [f"{path or '<root>'}: both sides reordered records "
                      "differently"]
    order = o_order if o_order != common else (
        t_order if t_order != common else common)
    order = [i for i in order
             if results.get(i) is not _DELETED and i in results]
    for seq in (ours_seq, theirs_seq):
        for rec_id in seq:
            if rec_id in results and results[rec_id] is not _DELETED \
                    and rec_id not in order:
                order.append(rec_id)
    return [results[i] for i in order], []


def _preservation_problems(base, side, merged, label: str) -> list[str]:
    """Verify every change *side* made to *base* survived into *merged*."""
    problems: list[str] = []

    def walk(b, s, m, path: str) -> None:
        if s == b:
            return
        if isinstance(s, dict) and isinstance(m, dict):
            bd = b if isinstance(b, dict) else {}
            for key, value in s.items():
                key_path = f"{path}.{key}" if path else str(key)
                if key not in bd or bd[key] != value:
                    if key not in m:
                        problems.append(f"{label} change lost: {key_path}")
                    else:
                        walk(bd.get(key, _MISSING), value, m[key], key_path)
            for key in bd:
                if key not in s and key in m:
                    problems.append(
                        f"{label} deletion lost: "
                        f"{f'{path}.{key}' if path else key}")
        elif _is_id_list(s) and isinstance(m, list) and _is_id_list(m):
            bm = {e["id"]: e for e in b} if _is_id_list(b) else {}
            mm = {e["id"]: e for e in m}
            for entry in s:
                rec_id = entry["id"]
                rec_path = f"{path}[{rec_id}]"
                if rec_id not in mm:
                    if rec_id not in bm or bm[rec_id] != entry:
                        problems.append(f"{label} record lost: {rec_path}")
                    continue
                walk(bm.get(rec_id, _MISSING), entry, mm[rec_id], rec_path)
            for rec_id in bm:
                if rec_id not in {e["id"] for e in s} and rec_id in mm:
                    problems.append(
                        f"{label} record deletion lost: {path}[{rec_id}]")
        elif s != m:
            # A bookkeeping timestamp both sides bumped is merged as the
            # later value, so the earlier one is intentionally not carried.
            if _bookkeeping_ts(path) and _merge_bookkeeping_ts(s, m) == m:
                return
            problems.append(
                f"{label} change not preserved at {path or '<root>'}")

    walk(base, side, merged, "")
    return problems


def _shape_problems(data) -> list[str]:
    """Read-only shape/status validation of the merged document.

    ``store``'s own validators cannot be reused here: they *normalize*
    (an invalid PR status silently becomes ``pending``) and raise on the
    first problem, while a resolution must refuse a document that is
    malformed on either side and report every problem to the agent.
    """
    from pm_core.pr_utils import VALID_PR_STATES
    from pm_core.store import VALID_PLAN_STATUSES

    if not isinstance(data, dict):
        return ["merged project.yaml is not a mapping"]
    problems: list[str] = []
    # ``store`` only ever sees a mapping here (it would raise on load), but a
    # hand-edited or generated side can carry anything: refuse it as a
    # problem instead of letting the serializer raise (``_yaml_dumper`` reads
    # ``project.libyaml``) and losing the readable conflict.
    project = data.get("project")
    if project is not None and not isinstance(project, dict):
        problems.append("merged project is not a mapping")
    prs = data.get("prs")
    pr_ids: set = set()
    if prs is not None:
        if not isinstance(prs, list):
            problems.append("merged prs is not a list")
        else:
            for entry in prs:
                if not isinstance(entry, dict) \
                        or not isinstance(entry.get("id"), str) \
                        or not entry["id"]:
                    problems.append("merged prs entry without a string id")
                    continue
                if entry["id"] in pr_ids:
                    problems.append(f"merged project.yaml has duplicate PR "
                                    f"id {entry['id']}")
                pr_ids.add(entry["id"])
                # Membership in a set needs a hashable value: a list/dict
                # status must read as an invalid one, not raise.
                status = entry.get("status")
                if not isinstance(status, str) \
                        or status not in VALID_PR_STATES:
                    problems.append(
                        f"merged PR {entry['id']} has invalid status "
                        f"{status!r}")
    plans = data.get("plans")
    plan_ids: set = set()
    parents: dict = {}
    if plans is not None:
        if not isinstance(plans, list):
            problems.append("merged plans is not a list")
        else:
            for entry in plans:
                if not isinstance(entry, dict) \
                        or not isinstance(entry.get("id"), str) \
                        or not entry["id"]:
                    problems.append("merged plans entry without a string id")
                    continue
                if entry["id"] in plan_ids:
                    problems.append(f"merged project.yaml has duplicate plan "
                                    f"id {entry['id']}")
                plan_ids.add(entry["id"])
                status = entry.get("status")
                if not isinstance(status, str) \
                        or status not in VALID_PLAN_STATUSES:
                    problems.append(
                        f"merged plan {entry['id']} has invalid status "
                        f"{status!r}")
                parent = entry.get("parent")
                if parent is not None and not isinstance(parent, str):
                    problems.append(
                        f"merged plan {entry['id']} has an invalid parent "
                        f"{parent!r}")
                parents[entry["id"]] = parent
            for plan_id, parent in parents.items():
                if isinstance(parent, str) and parent not in plan_ids:
                    problems.append(
                        f"merged plan {plan_id} references missing parent "
                        f"{parent!r}")
            for plan_id in plan_ids:
                seen: set = set()
                current = plan_id
                # A non-string parent was already refused above; do not walk
                # through it (it may be unhashable).
                while isinstance(current, str):
                    if current in seen:
                        problems.append(
                            f"merged plans have a cycle involving {plan_id}")
                        break
                    seen.add(current)
                    current = parents.get(current)
    return problems


def _resolution_digest(resolution: dict | None) -> str | None:
    """Canonical digest of a resolution's identity-bearing fields.

    The digest is computed over the *compact* projection (the form stored in
    ``project.yaml``), not the raw record: a re-check after pm applied the
    resolution carries the compact form forward (``_record_check``), and the
    two must hash identically or a benign re-check would look like a changed
    resolution and invalidate the approval.  The artifact path is excluded
    because it is host-specific, not part of the resolution's identity.
    """
    if not resolution:
        return None
    payload = _compact_resolution(resolution)
    payload.pop("diff_path", None)
    return hashlib.sha256(
        json.dumps(payload, sort_keys=True, default=str).encode()).hexdigest()


# --- base interaction summary ---------------------------------------------
# A clean git merge is not automatically behaviour-neutral: a new base can
# change model settings, dependencies, statuses or other configuration that
# changes what the PR's evidence actually exercised.  PM surfaces those
# changes; the sign-off agent decides whether they need a follow-up stage.

_CONFIG_NAMES = {"pyproject.toml", "setup.py", "setup.cfg", "package.json",
                 "Dockerfile", "install.sh", "Makefile"}
_PROJECT_BEHAVIOR_KEYS = ("model_config", "skip_qa", "base_branch", "backend",
                          "nested_podman", "libyaml")
_PR_BEHAVIOR_FIELDS = ("status", "depends_on", "model", "session_models",
                       "plan")


def base_behavior_changes(workdir: str, merge_base: str,
                          base_sha: str, pr: dict | None = None) -> list[str]:
    """Human-readable behavioural changes the new base brings, or [].

    *pr* (the PR being integrated) focuses the project.yaml part on records
    that can affect it — its own entry, its dependencies and its plan —
    instead of listing every other PR's status churn.
    """
    r = _git("diff", "--name-only", merge_base, base_sha, cwd=workdir)
    changed = [p for p in (r.stdout or "").splitlines() if p.strip()]
    out: list[str] = []
    for path in changed:
        if Path(path).name == "project.yaml":
            out.extend(_project_yaml_behavior_changes(
                workdir, merge_base, base_sha, path, pr=pr))
        elif _is_config_path(path):
            out.append(f"`{path}` changed on the base")
    return out[:500]


def _is_config_path(path: str) -> bool:
    name = Path(path).name
    return (name in _CONFIG_NAMES
            or (name.startswith("requirements")
                and name.endswith((".txt", ".in")))
            or path.startswith(".github/workflows/"))


def _show_yaml(workdir: str, rev: str, path: str):
    r = _git("show", f"{rev}:{path}", cwd=workdir)
    if r.returncode != 0:
        return None
    try:
        return _yaml_load(r.stdout or "") or {}
    except yaml.YAMLError:
        return None


def _short(value) -> str:
    text = json.dumps(value, default=str)
    return text if len(text) <= 80 else text[:77] + "..."


def _diff_leaves(old, new, path: str, out: list[str]) -> None:
    if isinstance(old, dict) and isinstance(new, dict):
        for key in list(old) + [k for k in new if k not in old]:
            _diff_leaves(old.get(key), new.get(key), f"{path}.{key}", out)
        return
    if old != new:
        out.append(f"{path} changed ({_short(old)} -> {_short(new)})")


def _project_yaml_behavior_changes(workdir: str, merge_base: str,
                                   base_sha: str, path: str,
                                   pr: dict | None = None) -> list[str]:
    old = _show_yaml(workdir, merge_base, path)
    new = _show_yaml(workdir, base_sha, path)
    if not isinstance(old, dict) or not isinstance(new, dict):
        return [f"`{path}` changed on the base"]
    out: list[str] = []
    # A malformed side (``project`` not a mapping) must not raise here: this
    # summary is what makes the agent weigh behaviour-relevant base changes,
    # so losing it silently would drop the justification requirement.
    old_project = old.get("project")
    new_project = new.get("project")
    old_project = old_project if isinstance(old_project, dict) else {}
    new_project = new_project if isinstance(new_project, dict) else {}
    for key in _PROJECT_BEHAVIOR_KEYS:
        if old_project.get(key) != new_project.get(key):
            if key == "model_config":
                _diff_leaves(old_project.get(key) or {},
                             new_project.get(key) or {},
                             f"`{path}`: project.model_config", out)
            else:
                out.append(
                    f"`{path}`: project.{key} changed "
                    f"({_short(old_project.get(key))} -> "
                    f"{_short(new_project.get(key))})")
    focus = (pr or {}).get("id")
    deps = {d for d in ((pr or {}).get("depends_on") or [])
            if isinstance(d, str)}
    focus_plan = (pr or {}).get("plan")

    def relevant(rec_id) -> bool:
        # Without a PR context list everything; with one, only records that
        # can gate or change this PR's run.
        return focus is None or rec_id == focus or rec_id in deps

    # Ids are used as dict keys: skip a malformed entry (a non-string id)
    # instead of raising on an unhashable one.
    old_prs = {p["id"]: p for p in old.get("prs") or []
               if isinstance(p, dict) and isinstance(p.get("id"), str)}
    new_prs = {p["id"]: p for p in new.get("prs") or []
               if isinstance(p, dict) and isinstance(p.get("id"), str)}
    for pr_id, entry in new_prs.items():
        if not pr_id or not relevant(pr_id):
            continue
        if pr_id not in old_prs:
            out.append(f"`{path}`: base added PR {pr_id} "
                       f"({entry.get('status')})")
            continue
        for field in _PR_BEHAVIOR_FIELDS:
            if old_prs[pr_id].get(field) != entry.get(field):
                out.append(
                    f"`{path}`: base changed {pr_id}.{field} "
                    f"({_short(old_prs[pr_id].get(field))} -> "
                    f"{_short(entry.get(field))})")
    for pr_id in old_prs:
        if pr_id not in new_prs and relevant(pr_id):
            out.append(f"`{path}`: base removed PR {pr_id}")
    old_plans = {p["id"]: p for p in old.get("plans") or []
                 if isinstance(p, dict) and isinstance(p.get("id"), str)}
    new_plans = {p["id"]: p for p in new.get("plans") or []
                 if isinstance(p, dict) and isinstance(p.get("id"), str)}
    for plan_id, entry in new_plans.items():
        if focus is not None and plan_id != focus_plan:
            continue
        if plan_id in old_plans \
                and old_plans[plan_id].get("status") != entry.get("status"):
            out.append(
                f"`{path}`: base changed plan {plan_id}.status "
                f"({old_plans[plan_id].get('status')} -> "
                f"{entry.get('status')})")
    return out


# --- candidate -------------------------------------------------------------

def is_ancestor(cwd, a: str, b: str) -> bool:
    """Whether *a* is an ancestor of (or equal to) *b* in *cwd*."""
    return _git("merge-base", "--is-ancestor", a, b, cwd=cwd).returncode == 0


@functools.lru_cache(maxsize=1)
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


def _worktree_merge(workdir: str, head: str, base_sha: str,
                    resolve: bool = False):
    """Merge in a temporary detached worktree.

    Returns ``(tree|None, conflicts, error, resolution|None)``.  With
    *resolve*, a conflict confined to ``project.yaml`` files is reconciled
    with :func:`resolve_project_yaml` in the same throwaway worktree.
    """
    with _repo_lock(workdir):
        return _worktree_merge_locked(workdir, head, base_sha, resolve)


def _worktree_merge_locked(workdir: str, head: str, base_sha: str,
                           resolve: bool = False):
    tmp = Path(tempfile.mkdtemp(prefix="pm-integrate-"))
    # A unique basename gives a unique admin dir (.git/worktrees/<name>).
    wt = tmp / f"candidate-{secrets.token_hex(4)}"
    no_hooks = ("-c", "core.hooksPath=/dev/null")
    try:
        add = _git(*no_hooks, "worktree", "add", "--detach", "--quiet",
                   str(wt), head, cwd=workdir)
        if add.returncode != 0:
            return None, [], f"candidate worktree failed: {_detail(add)}", None
        # rerere off: the rr-cache is shared with the PR worktree, and a
        # replayed resolution would make the candidate depend on local
        # history (with rerere.autoUpdate it stages the replayed paths, so a
        # conflict surfaces as an unexplained "candidate merge failed").
        m = _git(*no_hooks, "-c", "rerere.enabled=false",
                 "-c", "user.name=pm", "-c", "user.email=pm@localhost",
                 "merge", "--no-commit", "--no-ff", "--no-edit", base_sha, cwd=wt)
        if m.returncode == 0:
            tree = _out(_git("write-tree", cwd=wt))
            return (tree or None), [], (None if tree else "write-tree failed"), None
        conflicts = _out(_git("diff", "--name-only", "--diff-filter=U", cwd=wt))
        if not conflicts:
            return None, [], f"candidate merge failed: {_detail(m)}", None
        conflicts = sorted(conflicts.splitlines())
        if resolve and _all_resolvable(conflicts):
            tree, resolution = _resolve_worktree_conflicts(
                wt, workdir, head, base_sha, conflicts)
            return tree, conflicts, None, resolution
        return None, conflicts, None, None
    finally:
        removed = _git("worktree", "remove", "--force", str(wt),
                       cwd=workdir).returncode == 0
        shutil.rmtree(tmp, ignore_errors=True)
        if not removed:
            _git("worktree", "prune", cwd=workdir)


def _all_resolvable(conflicts: list[str]) -> bool:
    """Only project.yaml conflicts can be resolved automatically."""
    return bool(conflicts) and all(
        Path(c).name == "project.yaml" for c in conflicts)


def _write_resolved(target: Path, text: str) -> None:
    """Write a resolved document, lifting then restoring pm's read-only mode.

    ``store.save`` leaves project.yaml read-only (0444) so casual manual
    edits are blocked; a resolved file must not silently end up writable.
    The write is atomic (temp file + rename) like ``store.save``: the apply
    path writes into the real PR workdir mid-merge, and an interrupted
    write must not leave a truncated project.yaml behind.
    """
    target.parent.mkdir(parents=True, exist_ok=True)
    tmp = target.with_name(f".{target.name}.pm-tmp")
    try:
        tmp.write_text(text, encoding="utf-8")
        os.replace(tmp, target)
    finally:
        # A failed write must not leave a stray temp file in the workdir.
        with contextlib.suppress(OSError):
            tmp.unlink(missing_ok=True)
    try:
        target.chmod(stat.S_IRUSR | stat.S_IRGRP | stat.S_IROTH)
    except OSError:
        pass


def _stage_text(cwd, path: str, stage: int) -> str | None:
    """Index stage *stage* of *path* as text (``None`` when absent)."""
    r = _git("show", f":{stage}:{path}", cwd=cwd)
    return r.stdout if r.returncode == 0 else None


def _unified_diff(old: str, new: str, fromfile: str, tofile: str) -> str:
    lines = list(difflib.unified_diff(
        (old or "").splitlines(), (new or "").splitlines(),
        fromfile=fromfile, tofile=tofile, lineterm="", n=3))
    if len(lines) > _DIFF_LINE_LIMIT:
        lines = lines[:_DIFF_LINE_LIMIT] + ["... (truncated)"]
    return "\n".join(lines)


def _resolve_worktree_conflicts(wt: Path, workdir: str, head: str,
                                base_sha: str, conflicts: list[str]):
    """Resolve every conflicted project.yaml in *wt*; ``(tree|None, record)``."""
    paths: list[dict] = []
    unresolved: list[dict] = []
    diff_parts: list[str] = []
    for path in conflicts:
        ours_text = _stage_text(wt, path, 2)
        theirs_text = _stage_text(wt, path, 3)
        base_text = _stage_text(wt, path, 1)
        try:
            merged, detail = resolve_project_yaml(
                base_text, ours_text, theirs_text)
        except Exception as e:  # a resolver bug must read as "unresolved"
            merged, detail = None, {"error": f"resolver raised: {e}"}
        detail = dict(detail or {})
        detail["path"] = path
        if merged is None:
            unresolved.append({
                "path": path,
                "conflicts": detail.get("conflicts")
                or [detail.get("error") or "unresolved"],
            })
            paths.append(detail)
            continue
        target = Path(wt, path)
        try:
            _write_resolved(target, merged)
        except OSError as e:
            unresolved.append({"path": path,
                               "conflicts": [f"cannot write resolved file: {e}"]})
            paths.append(detail)
            continue
        add = _git("add", "--", path, cwd=wt)
        if add.returncode != 0:
            unresolved.append({"path": path,
                               "conflicts": [f"git add failed: {_detail(add)}"]})
            paths.append(detail)
            continue
        detail["resolver"] = "project-yaml-records/v1"
        detail["blob"] = _out(_git("rev-parse", f":{path}", cwd=wt)) or None
        actions = detail.get("actions") or {}
        detail["records"] = _record_counts(actions)
        detail["added_ours"] = _action_ids(actions, "added", "PR branch")
        detail["added_theirs"] = _action_ids(actions, "added", "new base")
        detail["merged_fields"] = _action_ids(actions, "changed")
        detail["removed"] = _action_ids(actions, "removed")
        diff_parts.append(f"### {path}")
        diff_parts.append(_unified_diff(
            ours_text or "", merged, f"{head[:12]}:{path} (PR branch)",
            f"{path} (resolved)"))
        diff_parts.append(_unified_diff(
            theirs_text or "", merged, f"{base_sha[:12]}:{path} (new base)",
            f"{path} (resolved)"))
        paths.append(detail)

    resolution: dict = {
        "resolver": "project-yaml-records/v1",
        "paths": paths,
        "unresolved": unresolved,
        "base_tree": _out(_git("rev-parse", f"{base_sha}^{{tree}}",
                               cwd=workdir)) or None,
        "head_tree": _out(_git("rev-parse", f"{head}^{{tree}}",
                               cwd=workdir)) or None,
        "diff": "\n".join(diff_parts).strip() + "\n" if diff_parts else "",
    }
    if unresolved:
        _git("merge", "--abort", cwd=wt)
        return None, resolution
    tree = _out(_git("write-tree", cwd=wt))
    if not tree:
        _git("merge", "--abort", cwd=wt)
        resolution["unresolved"].append(
            {"path": "*", "conflicts": ["git write-tree failed"]})
        return None, resolution
    resolution["candidate_tree"] = tree
    return tree, resolution


def _action_ids(actions: dict, kind: str, side: str | None = None) -> list[str]:
    """Flatten record actions into the ids they touched.

    A nested list's ids are qualified with their path
    (``prs[pr-200].notes:note-1``) so a resolution that only merged notes
    inside an existing record is still visible in the summary instead of
    looking like nothing happened.
    """
    out: list[str] = []
    for path, entry in actions.items():
        if kind == "added":
            values = (entry.get("added") or {}).get(side) or []
        else:
            values = entry.get(kind) or []
        if "[" in path or "." in path:
            values = [f"{path}:{v}" for v in values]
        out.extend(values)
    return sorted({str(i) for i in out})


def _record_counts(actions: dict) -> dict:
    """Bounded record counts for the compact summary."""
    out: dict = {}
    for path, entry in actions.items():
        added = entry.get("added") or {}
        out[path] = {
            "added_ours": len(added.get("PR branch") or []),
            "added_theirs": len(added.get("new base") or []),
            "changed": len(entry.get("changed") or []),
            "removed": len(entry.get("removed") or []),
        }
    return out


def compute_candidate(workdir: str, head: str, base_sha: str,
                      *, resolve: bool = True, pr: dict | None = None) -> dict:
    """Integration of *head* with *base_sha*, without touching the worktree.

    Returns ``{status, candidate_tree, conflicts, merge_base, base_files,
    pr_files, overlap, resolution?, base_behavior_changes, error?}``.  With
    *resolve*, a conflict confined to ``project.yaml`` is reconciled by
    record id in an isolated worktree; real conflicts are left alone.
    """
    out: dict = {"conflicts": [], "base_files": [], "pr_files": [],
                 "overlap": [], "candidate_tree": None,
                 "resolution": None, "base_behavior_changes": []}
    mb = _out(_git("merge-base", head, base_sha, cwd=workdir))
    out["merge_base"] = mb or None
    if mb:
        base_files = _out(_git("diff", "--name-only", mb, base_sha, cwd=workdir))
        pr_files = _out(_git("diff", "--name-only", mb, head, cwd=workdir))
        out["base_files"] = base_files.splitlines() if base_files else []
        out["pr_files"] = pr_files.splitlines() if pr_files else []
        out["overlap"] = sorted(set(out["base_files"]) & set(out["pr_files"]))
        if out["base_files"] and pr is not None:
            try:
                out["base_behavior_changes"] = base_behavior_changes(
                    workdir, mb, base_sha, pr=pr)
            except Exception as e:  # never fail the check on the summary
                _log.warning("base interaction summary failed: %s", e)
                out["base_behavior_error"] = str(e)

    # In-base first: a HEAD equal to the base (a PR with no commits of its
    # own) is "contained", not "up to date" — there is nothing to publish.
    if is_ancestor(workdir, head, base_sha):
        out["status"] = IN_BASE
        return out
    if is_ancestor(workdir, base_sha, head):
        out["status"] = UP_TO_DATE
        out["candidate_tree"] = _out(_git("rev-parse", f"{head}^{{tree}}",
                                          cwd=workdir)) or None
        return out

    resolution = None
    if _git_version() >= (2, 38):
        tree, conflicts, err = _merge_tree(workdir, head, base_sha)
        if not err and conflicts and resolve and _all_resolvable(conflicts):
            wtree, _wconf, werr, resolution = _worktree_merge(
                workdir, head, base_sha, resolve=True)
            if werr:
                resolution = dict(resolution or {})
                resolution.setdefault("unresolved", []).extend(
                    {"path": p, "conflicts": [werr]} for p in conflicts)
                resolution["error"] = werr
                tree = None
            else:
                tree = wtree
    else:
        tree, conflicts, err, resolution = _worktree_merge(
            workdir, head, base_sha, resolve=resolve)
    if err:
        out.update(status=ERROR, error=err)
    elif conflicts:
        # ``resolved`` is only meaningful with a resolution record that has
        # no unresolved entries: merge-tree and the worktree merge can
        # disagree, and a bare tree would be reported as an approved
        # resolution with no provenance.
        if tree and resolution and not resolution.get("unresolved"):
            out.update(status=RESOLVED, conflicts=conflicts,
                       candidate_tree=tree, resolution=resolution)
        else:
            out.update(status=CONFLICT, conflicts=conflicts,
                       resolution=resolution)
    else:
        out.update(status=CLEAN, candidate_tree=tree)
    return out


# --- check + record --------------------------------------------------------

def run_check(data: dict, pr: dict, root: Path | None = None,
              *, resolve: bool = True, base_sha: str | None = None) -> dict:
    """Fetch the base and compute the candidate for *pr* (no state writes).

    *base_sha* re-checks against an already-fetched revision instead of
    fetching again (used right after applying a resolution, so the record
    and the applied merge name the same base).
    """
    record: dict = {"checked_at": _now()}
    workdir = pr.get("workdir")
    if not workdir or not Path(workdir).is_dir():
        workdir = _cwd_checkout_of(pr)
    try:
        # The target comes from the checkout actually used (its origin), so
        # an in-container re-check resolves it from its own worktree.
        target_repo, base_branch = target_for(
            data, dict(pr, workdir=workdir), root)
    except Exception as e:  # repo dir resolution is best-effort
        target_repo, base_branch = "", (data.get("project") or {}).get(
            "base_branch", "master")
        _log.warning("integration target for %s: %s", pr.get("id"), e)
    record.update(target_repo=target_repo, base_branch=base_branch)
    if not workdir:
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
    if base_sha is None:
        base_sha, err = fetch_base(workdir, target_repo, base_branch)
        if err:
            record["base_sha"] = None
            record.update(status=ERROR, error=err)
            return record
    record["base_sha"] = base_sha
    record.update(compute_candidate(workdir, head, base_sha, resolve=resolve,
                                    pr=pr))
    return record


def _cwd_checkout_of(pr: dict) -> str | None:
    """The current directory's checkout when it is on the PR's branch.

    Lets the sign-off agent re-check from its own worktree (e.g. inside a
    container, where the recorded host workdir path does not exist).
    """
    top = _out(_git("rev-parse", "--show-toplevel", cwd=None))
    if not top or not pr.get("branch"):
        return None
    cur = _out(_git("rev-parse", "--abbrev-ref", "HEAD", cwd=top))
    return top if cur == pr["branch"] else None


def compact(record: dict) -> dict:
    """The project.yaml form of an integration record (lists truncated)."""
    out = {k: v for k, v in record.items()
           if k not in ("base_files", "pr_files", "resolution")}
    for k in ("conflicts", "overlap"):
        vals = list(record.get(k) or [])
        out[k] = vals[:_YAML_LIST_LIMIT]
        if len(vals) > _YAML_LIST_LIMIT:
            out[f"{k}_total"] = len(vals)
    # ``compact`` also runs on an already-compact record (a bounce re-records
    # the applied candidate, see signoff._record_applied_integration): the
    # full ``base_files`` list is gone there, so keep the recorded count
    # instead of resetting it to 0.
    if record.get("base_files") is not None:
        out["base_files_count"] = len(record["base_files"])
    else:
        out["base_files_count"] = int(record.get("base_files_count") or 0)
    resolution = record.get("resolution")
    if resolution:
        out["resolution"] = _compact_resolution(resolution)
    behavior = list(record.get("base_behavior_changes") or [])
    out["base_behavior_changes"] = behavior[:_BEHAVIOR_LIMIT]
    if len(behavior) > _BEHAVIOR_LIMIT:
        out["base_behavior_count"] = len(behavior)
    out["resolution_digest"] = _resolution_digest(resolution)
    return out


def _compact_resolution(resolution: dict) -> dict:
    out: dict = {}
    for key in ("resolver", "base_tree", "head_tree", "candidate_tree",
                "applied_merge_sha", "resolved_from", "diff_path", "error"):
        if resolution.get(key) is not None:
            out[key] = resolution[key]
    paths = []
    for entry in resolution.get("paths") or []:
        records = dict(entry.get("records") or {})
        # Bound the per-record counts too (a large conflict can touch every
        # record).  A recorded total is carried through re-compaction so the
        # resolution digest stays stable.
        records_total = entry.get("records_total")
        if records_total is None and len(records) > _YAML_LIST_LIMIT:
            records_total = len(records)
        if records_total is not None:
            records = dict(list(records.items())[:_YAML_LIST_LIMIT])
        item = {
            "path": entry.get("path"),
            "resolver": entry.get("resolver"),
            "blob": entry.get("blob"),
            "added_ours": list(entry.get("added_ours") or [])[:20],
            "added_theirs": list(entry.get("added_theirs") or [])[:20],
            "merged_fields": list(entry.get("merged_fields") or [])[:20],
            "removed": list(entry.get("removed") or [])[:20],
            "records": records,
        }
        if records_total is not None:
            item["records_total"] = records_total
        paths.append(item)
    out["paths"] = paths[:_YAML_LIST_LIMIT]
    unresolved = list(resolution.get("unresolved") or [])
    unresolved_total = resolution.get("unresolved_total")
    if unresolved_total is None and len(unresolved) > _YAML_LIST_LIMIT:
        unresolved_total = len(unresolved)
    out["unresolved"] = unresolved[:_YAML_LIST_LIMIT]
    if unresolved_total is not None:
        out["unresolved_total"] = unresolved_total
    return out


def integration_json_path(pr_id: str) -> Path | None:
    from pm_core.paths import captures_root
    croot = captures_root()
    return croot / pr_id / "integration.json" if croot else None


def resolution_diff_path(pr_id: str) -> Path | None:
    from pm_core.paths import captures_root
    croot = captures_root()
    return croot / pr_id / "integration-resolution.diff" if croot else None


def write_resolution_delta(pr_id: str, record: dict) -> str | None:
    """Write the human-readable resolution delta for *record*.

    Returns the delta's path, or None when the record carries no resolution
    (or only an empty delta).  Shared by the recorded artifact write and the
    read-only ``pm pr signoff integrate`` surface: the check records nothing
    on the PR, but the delta its output names must be inspectable on disk.
    """
    resolution = record.get("resolution") or {}
    diff = resolution.get("diff")
    diff_path = resolution_diff_path(pr_id)
    if diff_path is not None and (diff or resolution.get("diff_path")):
        try:
            diff_path.parent.mkdir(parents=True, exist_ok=True)
            if diff:
                diff_path.write_text(diff)
            resolution["diff_path"] = str(diff_path)
        except OSError as e:
            _log.warning("integration resolution diff for %s: %s", pr_id, e)
    return resolution.get("diff_path")


def _write_artifacts(pr_id: str, record: dict) -> None:
    """Write the full record + the human-readable resolution delta."""
    # The delta first: the full record written below must carry the pointer
    # to it (the compact state in project.yaml carries the same pointer).
    write_resolution_delta(pr_id, record)
    path = integration_json_path(pr_id)
    if path is not None:
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(json.dumps(record, indent=2) + "\n")
        except OSError as e:
            _log.warning("integration.json for %s: %s", pr_id, e)


def _carry_forward(record: dict, pr_entry: dict) -> dict:
    """Carry provenance from *pr_entry*'s stored record onto *record*.

    A re-check after pm applied a resolved candidate sees a clean/up-to-date
    merge; the resolution that produced the applied head must stay visible
    (and bound), so it is carried when the applied merge is an ancestor of
    the new HEAD.
    """
    old = pr_entry.get("integration") or {}
    if not record.get("resolution") and old.get("resolution"):
        applied = (old.get("resolution") or {}).get("applied_merge_sha")
        workdir = pr_entry.get("workdir")
        if not workdir or not Path(workdir).is_dir():
            # ``run_check`` may have computed this check from the current
            # checkout when the recorded workdir is not visible (e.g. inside
            # a container); resolve the ancestry from that same checkout so
            # the applied resolution is not silently dropped.
            workdir = _cwd_checkout_of(pr_entry)
        new_head = record.get("head")
        if applied and workdir and new_head and Path(workdir).is_dir() \
                and (applied == new_head
                     or is_ancestor(workdir, applied, new_head)):
            carried = dict(old["resolution"])
            carried.pop("diff", None)      # compact state never holds it
            diff_path = carried.get("diff_path")
            if diff_path:
                # Keep the full record's delta in integration.json: the
                # artifact is rewritten below, and the compact state only
                # carries the pointer.
                with contextlib.suppress(OSError):
                    carried["diff"] = Path(diff_path).read_text()
            record["resolution"] = carried
            record["resolution_digest"] = _resolution_digest(carried)
            record["resolved_from"] = carried.get("resolved_from")
            old_behavior = list(old.get("base_behavior_changes") or [])
            if old_behavior:
                record["base_behavior_changes"] = list(dict.fromkeys(
                    old_behavior + list(record.get("base_behavior_changes")
                                        or [])))
    elif record.get("status") == ERROR \
            and not record.get("base_behavior_changes") \
            and old.get("base_behavior_changes") \
            and record.get("head") and record.get("head") == old.get("head"):
        # A transient failure (e.g. the base fetch) must not drop the
        # behavioural changes the approval was required to assess: the
        # merge gate would then no longer ask for the evidence statement.
        record["base_behavior_changes"] = list(old["base_behavior_changes"])
    return record


def _check_is_stale(record: dict, pr_entry: dict) -> bool:
    """Whether *record* was computed before a concurrent actor moved HEAD.

    A check that starts before a parallel apply reads the old HEAD but can
    finish (and try to record) after it.  That record describes a revision
    the branch no longer has, so it must not overwrite the record that
    describes the revision the branch is on now.
    """
    old = pr_entry.get("integration") or {}
    workdir = pr_entry.get("workdir")
    if not workdir or not Path(workdir).is_dir():
        return False
    now = _out(_git("rev-parse", "HEAD", cwd=workdir))
    head = record.get("head")
    if not now or not head or now == head:
        return False
    return old.get("head") == now


def _record_check(root: Path, pr_id: str, record: dict) -> dict:
    """Record *record* on the PR, carrying resolution provenance forward.

    The carry-forward runs again inside the locked update.  Two operators can
    run ``--apply``/``--record`` at once, and one can store an applied record
    between this check's read and its write; overwriting that with a bare
    up-to-date record would lose the applied revision and its provenance (a
    later ``--record`` cannot restore them once the branch carries the base).
    A check computed before the HEAD moved is dropped the same way: it must
    not replace the record that describes the branch's current revision.
    """
    try:
        old_pr = store.get_pr(store.load(root), pr_id) or {}
    except Exception:
        old_pr = {}
    _carry_forward(record, old_pr)

    # Compute the digest before writing the artifact: integration.json is the
    # full record a person assesses, and it must carry the digest of the
    # resolution it describes (a later re-check/binding compares it).
    # ``_write_artifacts`` also records the diff path the compact state
    # carries (the full diff itself never goes into project.yaml); the digest
    # ignores that host-specific path.
    record["resolution_digest"] = _resolution_digest(record.get("resolution"))
    resolution = record.get("resolution")
    if resolution and not resolution.get("diff_path") \
            and resolution.get("diff"):
        # Set it before compaction so the compact record carries the pointer;
        # the file itself is written with the artifact below.  Only a record
        # with an actual delta gets a pointer: a failed attempt retains its
        # unresolved conflicts but has nothing to write, and naming a file
        # that does not exist would send the agent to an empty path.
        path = resolution_diff_path(pr_id)
        if path is not None:
            resolution["diff_path"] = str(path)

    final = {"record": record, "stale": False}

    def _apply(d):
        p = store.get_pr(d, pr_id)
        if p is None:
            return
        if _check_is_stale(record, p):
            # Keep the record that describes the branch's current revision
            # (and its applied resolution).
            final["record"] = p.get("integration") or record
            final["stale"] = True
            return
        merged = _carry_forward(record, p)
        merged["resolution_digest"] = _resolution_digest(
            merged.get("resolution"))
        p["integration"] = compact(merged)
        final["record"] = merged

    store.locked_update(root, _apply)
    final_record = final["record"]
    if final["stale"]:
        # The stored record (and the winner's artifact) is the one that
        # describes the branch; do not overwrite either.
        return final_record
    _write_artifacts(pr_id, final_record)
    return final_record


def check_integration(root: Path, pr_id: str, *, data: dict | None = None,
                      resolve: bool = True,
                      base_sha: str | None = None) -> dict:
    """Run the integration check for *pr_id* and record it.

    Writes ``pr["integration"]`` (compact) and ``$CAP/integration.json``
    (full), plus the resolution delta when there was one.  Never raises for
    git/network problems: they come back as ``status: error``.
    """
    if data is None:
        data = store.load(root)
    pr = store.get_pr(data, pr_id)
    if pr is None:
        raise ValueError(f"PR {pr_id} not found")
    record = run_check(data, pr, root, resolve=resolve, base_sha=base_sha)
    _log.info("integration %s: %s base=%s head=%s", pr_id, record.get("status"),
              (record.get("base_sha") or "")[:8], (record.get("head") or "")[:8])
    return _record_check(root, pr_id, record)


def prepare(root: Path, pr_id: str, *, data: dict | None = None) -> dict:
    """Sign-off's integration step: check, apply a resolution, re-check.

    A metadata-only conflict is resolved in the isolated candidate, then the
    same deterministic resolution is applied to the PR branch (so every
    backend can publish the candidate; GitHub refuses a conflicted branch).
    The branch is re-checked afterwards and the resolution provenance is
    carried onto the clean/up-to-date record the sign-off verdict binds to.
    A workdir that cannot take the merge keeps the ``resolved`` record plus
    ``apply_error``; sign-off cannot approve it.  When the apply lost a race
    with a concurrent apply (the PR HEAD moved under it), the revision the
    branch now has is re-checked and recorded instead, so the winner's
    applied record is never overwritten by the loser's stale one.
    """
    record = check_integration(root, pr_id, data=data)
    if record.get("status") != RESOLVED:
        return record
    try:
        merged, err = apply_integration(root, pr_id, record)
    except Exception as e:  # an apply bug must not crash the sign-off launch
        merged, err = None, f"applying the resolution raised: {e}"
    if not merged:
        record["apply_error"] = err
        _log.warning("sign-off %s: resolved integration not applied: %s",
                     pr_id, err)
        # Two operators can run ``--apply`` at the same time.  The loser's
        # apply fails once the winner has moved the PR HEAD; recording the
        # loser's *stale* resolved check would then overwrite the winner's
        # applied record — a lost update that drops the applied revision and
        # the resolution provenance (a later ``--record`` cannot restore
        # them once the branch already carries the base).  When the branch
        # now has a different revision, re-check that revision and record
        # it; ``_record_check`` carries the winner's applied resolution
        # forward onto the up-to-date record.
        if err in (HEAD_MOVED, HEAD_MOVED_APPLYING):
            fresh = store.load(root)
            pr_now = store.get_pr(fresh, pr_id)
            if pr_now is not None:
                current = run_check(fresh, pr_now, root,
                                    base_sha=record.get("base_sha"))
                if (current.get("status") in MERGEABLE
                        and current.get("head") != record.get("head")):
                    _log.info("sign-off %s: HEAD moved during apply; recorded "
                              "%s at %s", pr_id, current.get("status"),
                              (current.get("head") or "")[:8])
                    return _record_check(root, pr_id, current)
        return _record_check(root, pr_id, record)
    previous = record
    # Re-check against the exact revision just applied, not a fresh fetch: a
    # base that moved during the apply must not silently make the recorded
    # candidate describe a different merge (the merge gate re-fetches and
    # returns the PR to sign-off if the base is no longer current).  This
    # uses ``run_check`` + a single ``_record_check`` instead of
    # ``check_integration`` so the re-check is written once *with* the
    # resolution: an intermediate record without it would lose the applied
    # provenance (and the explicit-reuse requirement with it) if pm died
    # between the two writes.
    fresh = store.load(root)
    pr_now = store.get_pr(fresh, pr_id)
    if pr_now is None:
        raise ValueError(f"PR {pr_id} not found")
    record = run_check(fresh, pr_now, root, base_sha=previous.get("base_sha"))
    resolution = dict(previous.get("resolution") or {})
    resolution["applied_merge_sha"] = merged
    resolution["resolved_from"] = {
        "head": previous.get("head"),
        "base_sha": previous.get("base_sha"),
        "merge_base": previous.get("merge_base"),
        "status": previous.get("status"),
    }
    record["resolution"] = resolution
    record["resolved_from"] = resolution["resolved_from"]
    # The post-apply check sees no base diff (the base is in the branch now),
    # but the base interactions the agent must assess are still relevant.
    record["base_behavior_changes"] = list(
        previous.get("base_behavior_changes") or [])
    _log.info("sign-off %s: resolved and applied %s@%s as %s", pr_id,
              previous.get("base_branch"),
              (previous.get("base_sha") or "")[:8], merged[:8])
    return _record_check(root, pr_id, record)


def binding(record: dict | None) -> dict | None:
    """The part of an integration record a sign-off verdict is bound to."""
    if not record:
        return None
    return {k: record.get(k) for k in BINDING_KEYS}


def valid_for(record: dict | None, head: str | None) -> bool:
    """Whether *record* is a mergeable integration check of *head*."""
    if not (record and head and record.get("head") == head
            and record.get("status") in MERGEABLE
            and record.get("base_sha") and record.get("candidate_tree")):
        return False
    if record.get("status") == RESOLVED:
        resolution = record.get("resolution") or {}
        if not resolution or resolution.get("unresolved"):
            return False
    return True


def _added_count(entry: dict, key: str) -> int:
    """Added-record count for one resolved path, nested lists included.

    ``records`` holds the per-path counts (notes, plan sub-lists, ...); the
    flat id lists only name top-level records, so a notes-only resolution
    would otherwise read "0 added".
    """
    records = entry.get("records") or {}
    if records:
        return sum(int(c.get(key) or 0) for c in records.values()
                   if isinstance(c, dict))
    return len(entry.get(key) or [])


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
    if status == RESOLVED:
        entries = (record.get("resolution") or {}).get("paths") or []
        paths = [p.get("path") for p in entries if p.get("path")]
        ours = sum(_added_count(p, "added_ours") for p in entries)
        theirs = sum(_added_count(p, "added_theirs") for p in entries)
        return (f"conflicts with {base} resolved by record "
                f"({', '.join(paths) or 'project.yaml'}; "
                f"{ours} added from PR, {theirs} from base)")
    if status == CONFLICT:
        files = record.get("conflicts") or []
        text = (f"CONFLICTS with {base}: {', '.join(files[:5])}"
                + (" ..." if len(files) > 5 else ""))
        unresolved = (record.get("resolution") or {}).get("unresolved") or []
        if unresolved:
            text += " (metadata resolution not possible)"
        return text
    if status == IN_BASE:
        return f"already contained in {base}"
    return f"integration check failed: {record.get('error') or 'unknown error'}"


# --- apply (PR branch only) -----------------------------------------------

def apply_integration(root: Path, pr_id: str, record: dict | None = None,
                      *, data: dict | None = None) -> tuple[str | None, str | None]:
    """Merge the recorded base revision into the PR branch.

    For a ``clean`` record this is a plain merge.  For a ``resolved`` record
    the same deterministic record-aware resolution is re-applied to the
    conflicted ``project.yaml`` files and the resulting tree must equal the
    recorded candidate tree before the merge is committed.

    Only for a record of the workdir's current HEAD, on the PR branch, with a
    clean tree and no merge in progress.  Returns ``(merge_sha, None)`` or
    ``(None, reason)``; a failed merge is aborted so no half-merge is left.
    Never touches the base branch and never pushes (the merge step pushes the
    approved PR head where needed).
    """
    if data is None:
        data = store.load(root)
    pr = store.get_pr(data, pr_id) or {}
    if record is None:
        record = pr.get("integration") or {}
    status = record.get("status")
    if status not in (CLEAN, RESOLVED):
        return None, f"integration is {status}, not clean/resolved"
    workdir = pr.get("workdir")
    if not workdir or not Path(workdir).is_dir():
        return None, "no PR workdir"
    head = _out(_git("rev-parse", "HEAD", cwd=workdir))
    if head != record.get("head"):
        return None, HEAD_MOVED
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
    if not base_sha:
        # A partial or hand-edited record cannot name the revision to merge;
        # refuse instead of crashing (this runs unattended at sign-off launch
        # and from `--apply`, both of which promise a reason, not a traceback).
        return None, "the integration record has no base revision"
    msg = (f"Integrate {record.get('base_branch')}@{base_sha[:8]} into "
           f"{branch or 'PR branch'}")
    if status == RESOLVED:
        return _apply_resolution(record, workdir, head, base_sha, msg)

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


def _apply_resolution(record: dict, workdir: str, head: str, base_sha: str,
                      msg: str):
    """Merge *base_sha* and re-apply the recorded project.yaml resolution."""
    no_hooks = ("-c", "core.hooksPath=/dev/null")
    expected = record.get("candidate_tree")
    resolution = record.get("resolution") or {}
    recorded = {p.get("path"): p for p in resolution.get("paths") or []}
    if _out(_git("rev-parse", "HEAD", cwd=workdir)) != head:
        # Re-check right before touching the worktree: the caller verified
        # HEAD, but another process may have moved it since.
        return None, HEAD_MOVED_APPLYING
    m = _git(*no_hooks, "-c", "rerere.enabled=false", "merge", "--no-commit",
             "--no-ff", base_sha, cwd=workdir)
    if m.returncode == 0:
        # The workdir merged without conflict (the base moved under the
        # recorded check, or the branch already carries the change): the
        # candidate must still match exactly.
        tree = _out(_git("write-tree", cwd=workdir))
        merging = _git("rev-parse", "-q", "--verify", "MERGE_HEAD",
                       cwd=workdir).returncode == 0
        if not expected or tree != expected:
            # Undo only this merge.  ``merge --abort`` restores the state
            # before it, while ``reset --hard head`` could discard a commit
            # another process made between the HEAD check and this merge.
            if merging:
                _git("merge", "--abort", cwd=workdir)
            return None, ("the resolved merge produced a different tree "
                          f"({(tree or '?')[:12]} != {(expected or '?')[:12]})")
        if not merging:
            # The branch already carries the base (a concurrent apply won
            # the race): there is nothing to commit, and resetting would
            # discard that merge.  Report the current head; the caller
            # re-checks and binds that revision.
            return _out(_git("rev-parse", "HEAD", cwd=workdir)) or None, None
        commit = _git(*no_hooks, "-c", "user.name=pm",
                      "-c", "user.email=pm@localhost",
                      "commit", "--no-edit", cwd=workdir)
        if commit.returncode != 0:
            _git("merge", "--abort", cwd=workdir)
            return None, f"merge commit failed: {_detail(commit)}"
        return _out(_git("rev-parse", "HEAD", cwd=workdir)) or None, None

    conflicts = _out(_git("diff", "--name-only", "--diff-filter=U", cwd=workdir))
    conflicts = sorted(conflicts.splitlines()) if conflicts else []
    if not conflicts:
        _git("merge", "--abort", cwd=workdir)
        return None, f"merge failed: {_detail(m)}"
    for path in conflicts:
        entry = recorded.get(path)
        if entry is None or Path(path).name != "project.yaml":
            _git("merge", "--abort", cwd=workdir)
            return None, (f"unexpected conflict in {path} (not part of the "
                          "recorded resolution)")
        try:
            merged, detail = resolve_project_yaml(
                _stage_text(workdir, path, 1),
                _stage_text(workdir, path, 2),
                _stage_text(workdir, path, 3))
        except Exception as e:  # never leave the workdir mid-merge
            _git("merge", "--abort", cwd=workdir)
            return None, f"resolution of {path} raised: {e}"
        if merged is None:
            _git("merge", "--abort", cwd=workdir)
            why = (detail or {}).get("conflicts") or [(detail or {}).get("error")]
            return None, f"resolution of {path} failed: {why}"
        target = Path(workdir, path)
        try:
            _write_resolved(target, merged)
        except OSError as e:  # never leave the workdir mid-merge
            _git("merge", "--abort", cwd=workdir)
            return None, f"cannot write the resolution of {path}: {e}"
        add = _git("add", "--", path, cwd=workdir)
        if add.returncode != 0:
            _git("merge", "--abort", cwd=workdir)
            return None, f"git add {path} failed: {_detail(add)}"
        blob = _out(_git("rev-parse", f":{path}", cwd=workdir))
        if entry.get("blob") and blob != entry["blob"]:
            _git("merge", "--abort", cwd=workdir)
            return None, (f"the resolution of {path} is not deterministic "
                          f"(blob {blob[:12]} != recorded "
                          f"{entry['blob'][:12]})")
    left = _out(_git("diff", "--name-only", "--diff-filter=U", cwd=workdir))
    if left:
        _git("merge", "--abort", cwd=workdir)
        return None, f"unresolved conflicts remain: {left.split()}"
    tree = _out(_git("write-tree", cwd=workdir))
    if not expected or tree != expected:
        _git("merge", "--abort", cwd=workdir)
        return None, ("the resolved merge produced a different tree "
                      f"({(tree or '?')[:12]} != {(expected or '?')[:12]})")
    commit = _git(*no_hooks, "-c", "user.name=pm", "-c", "user.email=pm@localhost",
                  "commit", "-m", msg, cwd=workdir)
    if commit.returncode != 0:
        _git("merge", "--abort", cwd=workdir)
        return None, f"merge commit failed: {_detail(commit)}"
    return _out(_git("rev-parse", "HEAD", cwd=workdir)) or None, None


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
