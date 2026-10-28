"""Provenance for persisted QA evidence (pr-1ae1d2d).

Every scenario record the QA orchestrator writes is stamped with the PR and
the QA *run* (``QALoopState.loop_id``) that produced it, and each run
publishes a manifest at the top of the PR's captures dir listing the
scenarios it owns.

Every ``*_dir`` / ``*_path`` helper here takes the **per-PR** captures dir —
what ``pm qa captures-path <pr>`` prints and what a container sees as
``/pm-captures`` — *not* ``paths.captures_root()``, which is its parent (the
dir holding one subdirectory per PR).  Handing the parent to these helpers
does not raise: ``read_manifest`` would silently find nothing and
``write_manifest`` would put one manifest, shared by every PR, at the
captures root.  That is why the parameter is named ``pr_captures_dir``.

Why this exists: a nested fake-Claude QA fixture driven inside an outer
scenario container, or an earlier implementation-verification run, could
leave records under ``captures/<pr>/scenarios/`` that were indistinguishable
from real coverage — ``scenario.json`` named no PR and no run, nothing said
which scenarios the run owned, and orphan directories stayed in the scenario
namespace. Report / dashboard / sign-off must read *this* module's
authoritative membership, never "a directory exists".

The routing half of that bug (``captures_dir`` must not hand the
``/pm-captures`` mount to a PR it doesn't belong to) lives in #264; this
module is the evidence half and composes with it: routing stops a foreign
write, provenance makes any write that still happens detectable and
non-authoritative.

No tmux / git / store dependencies: this is a pure filesystem reader and
writer so it is unit-testable and usable from the host orchestrator, a
container session, and a CLI reader alike.
"""

from __future__ import annotations

import json
import logging
import os
import re
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

_log = logging.getLogger("pm.captures")

# Bumped only when the on-disk shape changes incompatibly.  Readers treat a
# record without ``schema`` as legacy (still readable, just unbound).
SCHEMA = 1

# The run manifest at the top of the PR's captures dir (beside report.html
# and integration.json — deliberately *not* inside ``scenarios/``, which is
# the per-scenario namespace agents walk).
MANIFEST_NAME = "qa_manifest.json"

# Per-run copy of the same manifest.  The root file is the "current run"
# pointer, and a nested fixture writing into the enclosing PR's tree can
# overwrite it; the per-run copies keep every run's authoritative membership
# recoverable (pr-1ae1d2d).
RUNS_DIR_NAME = "qa_runs"

# Per-scenario structured record written by
# ``qa_loop._persist_scenario_verdicts``.
SCENARIO_RECORD_NAME = "scenario.json"

# Where provably-foreign scenario directories are moved (never deleted).
FOREIGN_DIR_NAME = "_foreign"

_NUMERIC_DIR_RE = re.compile(r"^\d+$")


# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------

def manifest_path(pr_captures_dir: Path | str) -> Path:
    """Path of the current-run manifest under *pr_captures_dir*."""
    return Path(pr_captures_dir) / MANIFEST_NAME


def run_manifest_path(pr_captures_dir: Path | str, run_id: str) -> Path:
    """Path of the per-run copy of a run's manifest."""
    return Path(pr_captures_dir) / RUNS_DIR_NAME / f"{run_id}.json"


def scenarios_dir(pr_captures_dir: Path | str) -> Path:
    """The per-scenario evidence namespace."""
    return Path(pr_captures_dir) / "scenarios"


def scenario_dir(pr_captures_dir: Path | str, index: int) -> Path:
    return scenarios_dir(pr_captures_dir) / str(index)


def scenario_record_path(pr_captures_dir: Path | str, index: int) -> Path:
    return scenario_dir(pr_captures_dir, index) / SCENARIO_RECORD_NAME


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _canonical_index(name: str) -> int | None:
    """The index a canonical numeric name means, or ``None``.

    Canonical means ``str(int(name)) == name`` — ``3``, not ``03``: every
    helper turns an index back into a path, so treating ``03`` as index 3
    would make :func:`quarantine_foreign` move ``scenarios/3`` on ``03``'s
    record.  ``int()`` itself raises on an absurdly long digit string
    (Python's int-from-str limit), which an untrusted tree can contain, so
    the conversion is guarded rather than assumed.
    """
    if not _NUMERIC_DIR_RE.match(name):
        return None
    try:
        value = int(name)
    except ValueError:
        return None
    return value if str(value) == name else None


def _atomic_write_json(path: Path, data: dict) -> bool:
    """Write *data* as JSON via ``tmp`` + ``rename``; False on any OSError.

    The temp name is unique per writer: two QA runs for the same PR can
    publish the manifest concurrently (a stale controller and a fresh one),
    and a shared ``<name>.tmp`` would let them truncate/rename each other's
    half-written file instead of the intended last-write-wins.
    """
    tmp: Path | None = None
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_name(
            f".{path.name}.{os.getpid()}.{uuid.uuid4().hex[:8]}.tmp")
        tmp.write_text(json.dumps(data, indent=2), encoding="utf-8")
        os.replace(tmp, path)
        return True
    except (OSError, TypeError, ValueError):
        _log.warning("Failed to write %s", path, exc_info=True)
        if tmp is not None:
            try:
                tmp.unlink()
            except OSError:
                pass
        return False


# ---------------------------------------------------------------------------
# Manifest
# ---------------------------------------------------------------------------

def write_manifest(pr_captures_dir: Path | str | None, *,
                   pr_id: str, run_id: str,
                   scenarios: list[dict] | None = None,
                   overall: str = "",
                   started_at: str | None = None) -> Path | None:
    """Publish the authoritative membership of the current QA run.

    Overwrites the previous run's manifest — "the current run" is exactly
    what readers need, and a report bound to a superseded run is then
    detectable by the mismatch (the report's ``pm-signoff-qa-run`` tag
    against this manifest; see ``signoff.merge_gate_refusal``).  *started_at* is
    carried over when the manifest already describes the same run, so the
    manifest does not claim the run restarted on every update.

    Best effort: returns ``None`` (and logs) rather than raising, because a
    missing manifest must never abort a QA run.
    """
    if pr_captures_dir is None or not pr_id or not run_id:
        return None
    path = manifest_path(pr_captures_dir)
    if started_at is None:
        previous = read_manifest(pr_captures_dir, pr_id=pr_id)
        if previous and previous.get("run_id") == run_id:
            started_at = previous.get("started_at")
    data = {
        "schema": SCHEMA,
        "pr_id": pr_id,
        "run_id": run_id,
        "started_at": started_at or _now(),
        "updated_at": _now(),
        "overall": overall or "",
        # Only mappings are members; a caller that hands over something else
        # must not turn "never raises" into a TypeError mid-QA-run.
        "scenarios": [dict(s) for s in (scenarios or [])
                      if isinstance(s, dict)],
    }
    # Per-run copy first: the root pointer below is what a nested fixture can
    # overwrite, and the copy is what makes this run's membership recoverable
    # afterwards.
    run_path = run_manifest_path(pr_captures_dir, run_id)
    if not _atomic_write_json(run_path, data):
        return None
    return path if _atomic_write_json(path, data) else run_path


def _valid_manifest(data, pr_id: str | None) -> dict | None:
    """Validate a parsed manifest; ``None`` when it is not a usable record."""
    if not isinstance(data, dict):
        return None
    owner = data.get("pr_id")
    if not isinstance(owner, str) or not owner:
        return None
    if pr_id is not None and owner != pr_id:
        return None
    if not isinstance(data.get("run_id"), str) or not data["run_id"]:
        return None
    scenarios = data.get("scenarios")
    if not isinstance(scenarios, list):
        scenarios = []
    # The manifest is untrusted input — a nested fixture or a hand-edited file
    # can write into this tree — so normalise the entries once, here, instead
    # of trusting every reader to be defensive.  Non-mappings are dropped; a
    # canonical numeric-string index (``"3"``) becomes the int every helper
    # turns back into a path.  Any other index value is kept on the member (so
    # the audit still lists it) but never matched to a directory: consumers go
    # through :func:`member_index`, which returns ``None`` for it.
    clean: list[dict] = []
    for entry in scenarios:
        if not isinstance(entry, dict):
            continue
        idx = entry.get("index")
        if isinstance(idx, str):
            coerced = _canonical_index(idx)
            if coerced is not None:
                entry = {**entry, "index": coerced}
        clean.append(entry)
    data["scenarios"] = clean
    return data


def member_index(entry) -> int | None:
    """The canonical scenario index of a manifest member, or ``None``.

    Membership lists come from the (untrusted) manifest, so consumers must not
    assume an index is an int: a list/dict value used to raise ``TypeError:
    unhashable type`` while building the membership set, crashing the very
    ``audit``/``pm qa evidence`` surface that exists to report a damaged tree.
    """
    idx = entry.get("index") if isinstance(entry, dict) else None
    return idx if isinstance(idx, int) and not isinstance(idx, bool) else None


def _read_json(path: Path):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def read_manifest(pr_captures_dir: Path | str | None,
                  *, pr_id: str | None = None,
                  run_id: str | None = None) -> dict | None:
    """Read a run manifest, or ``None`` when none is usable for *pr_id*.

    Resolution order:

    1. The root ``qa_manifest.json`` (the current-run pointer).
    2. ``qa_runs/<run_id>.json`` when *run_id* is given.
    3. The newest ``qa_runs/*.json`` naming *pr_id*.

    *pr_id* validates ownership: a nested fixture can write a manifest into
    the enclosing PR's tree, so a manifest naming another PR is never
    trusted.  Steps 2 and 3 are what make this PR's membership survive a
    fixture overwriting the root pointer mid-run.
    """
    if pr_captures_dir is None:
        return None
    root = Path(pr_captures_dir)
    manifest = _valid_manifest(_read_json(manifest_path(root)), pr_id)
    if manifest is not None:
        return manifest
    if run_id:
        manifest = _valid_manifest(
            _read_json(run_manifest_path(root, run_id)), pr_id)
        if manifest is not None:
            return manifest
    runs = root / RUNS_DIR_NAME
    try:
        files = [p for p in runs.glob("*.json") if p.is_file()]
    except OSError:
        return None
    # A per-run copy can vanish between the glob and the stat (a concurrent
    # prune); sort it to the back rather than discarding every candidate.
    candidates = sorted(files, key=_mtime_or_zero, reverse=True)
    for path in candidates:
        manifest = _valid_manifest(_read_json(path), pr_id)
        if manifest is not None:
            return manifest
    return None


def _mtime_or_zero(path: Path) -> float:
    try:
        return path.stat().st_mtime
    except OSError:
        return 0.0


def _manifest_owner(data) -> str:
    """A manifest file's claimed owner, for an anomaly that has to name it."""
    owner = data.get("pr_id") if isinstance(data, dict) else None
    return owner if isinstance(owner, str) and owner else "no PR"


# ---------------------------------------------------------------------------
# Per-scenario records
# ---------------------------------------------------------------------------

def read_scenario_record(pr_captures_dir: Path | str | None,
                         index: int) -> dict | None:
    """The scenario's structured record, or ``None`` when absent/unreadable."""
    if pr_captures_dir is None:
        return None
    path = scenario_record_path(pr_captures_dir, index)
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return data if isinstance(data, dict) else None


def write_scenario_record(pr_captures_dir: Path | str | None, index: int,
                          record: dict, *,
                          pr_id: str, run_id: str) -> Path | None:
    """Write ``scenarios/<index>/scenario.json`` with PR/run identity.

    The caller's keys are preserved (the sign-off agent reads
    ``index/title/focus/steps/verdict/reason``); ``schema``, ``pr_id``,
    ``run_id`` and ``captured_at`` are added.
    """
    if pr_captures_dir is None:
        return None
    stamped = dict(record)
    stamped.update({
        "schema": SCHEMA,
        "pr_id": pr_id,
        "run_id": run_id,
        "captured_at": _now(),
    })
    path = scenario_record_path(pr_captures_dir, index)
    return path if _atomic_write_json(path, stamped) else None


# ---------------------------------------------------------------------------
# Audit
# ---------------------------------------------------------------------------

CURRENT = "current"
PRIOR_RUN = "prior-run"
FOREIGN = "foreign"
UNOWNED = "unowned"


@dataclass
class ScenarioDirEvidence:
    """What one ``scenarios/<n>/`` directory claims about its owner."""
    index: int
    state: str
    owner_pr: str = ""
    owner_run: str = ""
    # Whether the directory holds a ``scenario.json`` at all.  A launched
    # scenario that never produced a verdict writes only ``prompt.md``; a
    # record with no ``pr_id``/``run_id`` is legacy or synthetic.  Both audit
    # as unowned, but they are different facts and the anomaly says which.
    has_record: bool = False


@dataclass
class EvidenceAudit:
    """Authoritative membership of a QA run, plus what else is on disk."""
    pr_captures_dir: Path | None
    pr_id: str
    run_id: str
    manifest: dict | None
    manifest_run: str
    members: list[dict] = field(default_factory=list)
    dirs: dict[int, ScenarioDirEvidence] = field(default_factory=dict)
    orphans: list[int] = field(default_factory=list)
    anomalies: list[str] = field(default_factory=list)


def scenario_indices(pr_captures_dir: Path | str | None) -> list[int]:
    """Indices of the numeric directories under ``scenarios/`` (sorted).

    Only *canonical* names count (``3``, not ``03``).  The index is what
    every other helper turns back into a path (``scenario_dir(root, 3)``),
    so accepting ``03`` as index 3 would make :func:`quarantine_foreign`
    move ``scenarios/3`` — a different directory — based on ``03``'s record.
    pm only ever writes ``str(index)``, so a non-canonical name is not ours
    to classify (or move).
    """
    if pr_captures_dir is None:
        return []
    root = scenarios_dir(pr_captures_dir)
    try:
        entries = list(root.iterdir())
    except OSError:
        return []
    out: list[int] = []
    for entry in entries:
        if not entry.is_dir():
            continue
        index = _canonical_index(entry.name)
        if index is not None:
            out.append(index)
    return sorted(out)


def _classify(pr_captures_dir: Path, index: int,
              pr_id: str, run_id: str) -> ScenarioDirEvidence:
    record = read_scenario_record(pr_captures_dir, index)
    owner_pr = (record or {}).get("pr_id") or ""
    owner_run = (record or {}).get("run_id") or ""
    if not isinstance(owner_pr, str):
        owner_pr = ""
    if not isinstance(owner_run, str):
        owner_run = ""
    if owner_pr and owner_pr != pr_id:
        state = FOREIGN
    elif owner_run and run_id and owner_run != run_id:
        state = PRIOR_RUN
    elif owner_run and run_id:
        state = CURRENT
    else:
        # No identity at all, or a run id with no current run to compare
        # against — either way nothing binds it to the run being audited.
        state = UNOWNED
    return ScenarioDirEvidence(index=index, state=state,
                               owner_pr=owner_pr, owner_run=owner_run,
                               has_record=record is not None)


def audit(pr_captures_dir: Path | str | None, *,
          pr_id: str, run_id: str = "") -> EvidenceAudit:
    """Authoritative membership for *run_id*, and every directory's claim.

    ``members`` comes from the run manifest — never from the directory
    listing.  Every ``scenarios/<n>/`` directory is classified so a caller
    can tell this run's evidence from an earlier run's, a foreign project's,
    or a legacy record with no identity at all.

    Directories are classified against the *manifest's* run whenever one is
    readable, because that is the run whose membership they are being
    compared with.  *run_id* is what the caller believes is current (the live
    ``qa_status.json``'s run); when it disagrees with the manifest, the
    disagreement is reported as an anomaly but the classification still
    follows the manifest — otherwise every member's own record would be
    reported as "prior run … this run's evidence is missing" directly beside
    a membership list that names that very run.
    """
    if pr_captures_dir is None:
        # No captures dir at all: nothing is bound to a run, and saying so is
        # the honest answer — never audit the process's current directory.
        return EvidenceAudit(
            pr_captures_dir=None, pr_id=pr_id, run_id=run_id, manifest=None,
            manifest_run="",
            anomalies=["no captures dir — no QA evidence to audit"])
    root = Path(pr_captures_dir)
    manifest = read_manifest(pr_captures_dir, pr_id=pr_id, run_id=run_id or None)
    manifest_run = (manifest or {}).get("run_id", "")
    effective_run = manifest_run or run_id
    # The root pointer is the "current run" file a nested fixture overwrites.
    # :func:`read_manifest` recovers this PR's membership from ``qa_runs/``
    # when that happens; the audit must say so rather than present recovered
    # data as the pointer's own content — the clobber is the incident's
    # signature, and this is the surface that has to show it.
    root_pointer = manifest_path(root)
    root_raw = _read_json(root_pointer) if root_pointer.is_file() else None
    root_ok = _valid_manifest(root_raw, pr_id) is not None
    members = [m for m in ((manifest or {}).get("scenarios") or [])
               if isinstance(m, dict)]
    dirs = {i: _classify(root, i, pr_id, effective_run)
            for i in scenario_indices(pr_captures_dir)}
    member_indices = {i for m in members if (i := member_index(m)) is not None}
    orphans = sorted(i for i in dirs if i not in member_indices)

    anomalies: list[str] = []
    if manifest is None:
        if root_raw is None:
            anomalies.append(
                "no qa_manifest.json — scenario membership is not run-bound")
        elif _manifest_owner(root_raw) == pr_id:
            anomalies.append(
                "the root qa_manifest.json is unusable (no run id) — "
                "scenario membership is not run-bound")
        else:
            anomalies.append(
                f"the root qa_manifest.json names {_manifest_owner(root_raw)}, "
                f"not {pr_id} — no run-bound membership for this PR")
    else:
        if run_id and manifest_run and manifest_run != run_id:
            anomalies.append(
                f"the manifest belongs to QA run {manifest_run}, "
                f"not {run_id}; the manifest is authoritative")
        if not root_ok:
            if root_raw is None:
                anomalies.append(
                    "no qa_manifest.json at the top of the captures dir — "
                    f"membership recovered from {RUNS_DIR_NAME}/")
            elif _manifest_owner(root_raw) == pr_id:
                anomalies.append(
                    "the root qa_manifest.json is unusable (no run id) — "
                    f"membership recovered from {RUNS_DIR_NAME}/")
            else:
                anomalies.append(
                    f"the root qa_manifest.json names "
                    f"{_manifest_owner(root_raw)}, not {pr_id} — a foreign "
                    "writer overwrote the current-run pointer; membership "
                    f"recovered from {RUNS_DIR_NAME}/")
    for i, ev in sorted(dirs.items()):
        if ev.state == FOREIGN:
            if i in member_indices:
                # The manifest says this run owns the scenario, but the only
                # record on disk belongs to another PR (a nested fixture that
                # overwrote this index during the run).  Its evidence is gone,
                # not merely someone else's — same rule as a prior-run member.
                anomalies.append(
                    f"scenarios/{i}: manifest member whose directory holds a "
                    f"foreign record (pr_id={ev.owner_pr}) — this run's "
                    "evidence for it is missing")
            else:
                anomalies.append(
                    f"scenarios/{i}: foreign record (pr_id={ev.owner_pr}) — "
                    "not this PR's evidence")
        elif ev.state == UNOWNED:
            if i in member_indices:
                # The manifest says this run owns the scenario, but nothing
                # on disk carries provenance: either no verdict was captured
                # (only ``prompt.md``) or the record predates provenance (a
                # pre-fix or synthetic fixture record).  Reporting either as
                # "not bound to a QA run" would contradict the membership the
                # same audit just printed.
                if ev.has_record:
                    anomalies.append(
                        f"scenarios/{i}: manifest member whose record carries "
                        "no PR/run identity (legacy or synthetic) — its files "
                        "cannot be verified as this run's evidence")
                else:
                    anomalies.append(
                        f"scenarios/{i}: manifest member with no provenance "
                        "record (no verdict captured) — its files cannot be "
                        "verified as this run's evidence")
            elif ev.owner_run:
                anomalies.append(
                    f"scenarios/{i}: record names QA run {ev.owner_run}, but "
                    "no current-run manifest binds it to this run")
            else:
                anomalies.append(
                    f"scenarios/{i}: unowned record (no PR/run identity) — "
                    "not bound to a QA run")
        elif ev.state == PRIOR_RUN:
            if i in member_indices:
                # The manifest says this run owns the scenario, but the only
                # record on disk was written by an earlier run — this run's
                # evidence for it is missing, not merely old.
                anomalies.append(
                    f"scenarios/{i}: manifest member whose record is from "
                    f"prior QA run {ev.owner_run} — this run's evidence for "
                    "it is missing")
            else:
                anomalies.append(
                    f"scenarios/{i}: prior QA run {ev.owner_run}")
    for i in orphans:
        if dirs[i].state == CURRENT:
            anomalies.append(
                f"scenarios/{i}: not in the current run's manifest")
    for m in members:
        idx = member_index(m)
        if idx is not None and idx not in dirs:
            # Membership without evidence: the run claims the scenario but
            # nothing is on disk — the report must not paper over it.
            anomalies.append(
                f"scenarios/{idx}: listed in the manifest but has no "
                "evidence directory — its evidence is missing")
    return EvidenceAudit(pr_captures_dir=root, pr_id=pr_id, run_id=effective_run,
                         manifest=manifest, manifest_run=manifest_run,
                         members=members, dirs=dirs, orphans=orphans,
                         anomalies=anomalies)


# ---------------------------------------------------------------------------
# Quarantine
# ---------------------------------------------------------------------------

def _free_target(base: Path) -> Path:
    if not base.exists():
        return base
    n = 1
    while True:
        candidate = base.with_name(f"{base.name}-{n}")
        if not candidate.exists():
            return candidate
        n += 1


def quarantine_foreign(pr_captures_dir: Path | str | None, *,
                       pr_id: str, run_id: str = "") -> list[Path]:
    """Move provably-foreign scenario dirs out of the scenario namespace.

    Only a record whose ``scenario.json`` names a *different* ``pr_id`` is
    moved — that is the one case where the directory is unambiguously not
    this PR's evidence.  Same-PR history from an earlier run and legacy
    records with no identity stay where they are (existing captures must be
    preserved); they are surfaced as anomalies by :func:`audit` instead.

    The move keeps every byte: the target is
    ``scenarios/_foreign/<run_id>-<index>`` (with a numeric suffix when that
    already exists).  Best effort — never raises.

    An empty *pr_id* quarantines nothing, for the same reason
    :func:`write_manifest` writes nothing without one: "another PR's record"
    is only defined relative to the PR we are, so without one *every*
    identity-carrying record would look foreign — and quarantine is a move,
    which the caller cannot undo.  A caller with no PR id has a bug; it must
    not turn that bug into displaced evidence.
    """
    if pr_captures_dir is None or not pr_id:
        return []
    root = Path(pr_captures_dir)
    moved: list[Path] = []
    label = run_id or "unknown-run"
    for index in scenario_indices(root):
        ev = _classify(root, index, pr_id, run_id)
        if ev.state != FOREIGN:
            continue
        source = scenario_dir(root, index)
        target = _free_target(scenarios_dir(root) / FOREIGN_DIR_NAME
                              / f"{label}-{index}")
        try:
            target.parent.mkdir(parents=True, exist_ok=True)
            os.replace(source, target)
        except OSError:
            _log.warning("Failed to quarantine foreign scenario dir %s",
                         source, exc_info=True)
            continue
        _log.info("Quarantined foreign scenario %d (owner pr=%s) -> %s",
                  index, ev.owner_pr, target)
        moved.append(target)
    return moved


# ---------------------------------------------------------------------------
# QA status binding
# ---------------------------------------------------------------------------

def status_run_id(status: dict | None, status_path: Path | str | None,
                  pr_id: str = "") -> str:
    """The QA run a ``qa_status.json`` belongs to (``""`` when unknown).

    The status file names its run (``run_id``, written by
    ``qa_loop._write_status_file``).  A legacy file written before that field
    existed still names it in its workdir path —
    ``~/.pm/workdirs/qa/<pr_id>-<run_id>/qa_status.json`` — so *pr_id* is
    needed to strip the prefix.  One implementation for every reader (the
    sign-off prompt, ``pm qa evidence``) so they cannot drift.
    """
    if isinstance(status, dict):
        run = status.get("run_id")
        if isinstance(run, str) and run:
            return run
    if status_path is None or not pr_id:
        return ""
    name = Path(status_path).parent.name
    run = name.removeprefix(f"{pr_id}-")
    return "" if run == name else run
