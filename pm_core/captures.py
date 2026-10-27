"""Provenance for persisted QA evidence (pr-1ae1d2d).

Every scenario record the QA orchestrator writes is stamped with the PR and
the QA *run* (``QALoopState.loop_id``) that produced it, and each run
publishes a manifest at the captures root listing the scenarios it owns.

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
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

_log = logging.getLogger("pm.captures")

# Bumped only when the on-disk shape changes incompatibly.  Readers treat a
# record without ``schema`` as legacy (still readable, just unbound).
SCHEMA = 1

# The run manifest at the captures root (beside report.html and
# integration.json — deliberately *not* inside ``scenarios/``, which is the
# per-scenario namespace agents walk).
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

def manifest_path(captures_root: Path | str) -> Path:
    """Path of the current-run manifest under *captures_root*."""
    return Path(captures_root) / MANIFEST_NAME


def run_manifest_path(captures_root: Path | str, run_id: str) -> Path:
    """Path of the per-run copy of a run's manifest."""
    return Path(captures_root) / RUNS_DIR_NAME / f"{run_id}.json"


def scenarios_dir(captures_root: Path | str) -> Path:
    """The per-scenario evidence namespace."""
    return Path(captures_root) / "scenarios"


def scenario_dir(captures_root: Path | str, index: int) -> Path:
    return scenarios_dir(captures_root) / str(index)


def scenario_record_path(captures_root: Path | str, index: int) -> Path:
    return scenario_dir(captures_root, index) / SCENARIO_RECORD_NAME


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _atomic_write_json(path: Path, data: dict) -> bool:
    """Write *data* as JSON via ``tmp`` + ``rename``; False on any OSError."""
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_name(path.name + ".tmp")
        tmp.write_text(json.dumps(data, indent=2), encoding="utf-8")
        os.replace(tmp, path)
        return True
    except (OSError, TypeError, ValueError):
        _log.warning("Failed to write %s", path, exc_info=True)
        try:
            path.with_name(path.name + ".tmp").unlink()
        except OSError:
            pass
        return False


# ---------------------------------------------------------------------------
# Manifest
# ---------------------------------------------------------------------------

def write_manifest(captures_root: Path | str | None, *,
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
    if captures_root is None or not pr_id or not run_id:
        return None
    path = manifest_path(captures_root)
    if started_at is None:
        previous = read_manifest(captures_root, pr_id=pr_id)
        if previous and previous.get("run_id") == run_id:
            started_at = previous.get("started_at")
    data = {
        "schema": SCHEMA,
        "pr_id": pr_id,
        "run_id": run_id,
        "started_at": started_at or _now(),
        "updated_at": _now(),
        "overall": overall or "",
        "scenarios": [dict(s) for s in (scenarios or [])],
    }
    # Per-run copy first: the root pointer below is what a nested fixture can
    # overwrite, and the copy is what makes this run's membership recoverable
    # afterwards.
    run_path = run_manifest_path(captures_root, run_id)
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
    if not isinstance(data.get("scenarios"), list):
        data["scenarios"] = []
    return data


def _read_json(path: Path):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def read_manifest(captures_root: Path | str | None,
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
    if captures_root is None:
        return None
    root = Path(captures_root)
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
        candidates = sorted(
            (p for p in runs.glob("*.json") if p.is_file()),
            key=lambda p: p.stat().st_mtime, reverse=True)
    except OSError:
        return None
    for path in candidates:
        manifest = _valid_manifest(_read_json(path), pr_id)
        if manifest is not None:
            return manifest
    return None


# ---------------------------------------------------------------------------
# Per-scenario records
# ---------------------------------------------------------------------------

def read_scenario_record(captures_root: Path | str | None,
                         index: int) -> dict | None:
    """The scenario's structured record, or ``None`` when absent/unreadable."""
    if captures_root is None:
        return None
    path = scenario_record_path(captures_root, index)
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return data if isinstance(data, dict) else None


def write_scenario_record(captures_root: Path | str | None, index: int,
                          record: dict, *,
                          pr_id: str, run_id: str) -> Path | None:
    """Write ``scenarios/<index>/scenario.json`` with PR/run identity.

    The caller's keys are preserved (the sign-off agent reads
    ``index/title/focus/steps/verdict/reason``); ``schema``, ``pr_id``,
    ``run_id`` and ``captured_at`` are added.
    """
    if captures_root is None:
        return None
    stamped = dict(record)
    stamped.update({
        "schema": SCHEMA,
        "pr_id": pr_id,
        "run_id": run_id,
        "captured_at": _now(),
    })
    path = scenario_record_path(captures_root, index)
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


@dataclass
class EvidenceAudit:
    """Authoritative membership of a QA run, plus what else is on disk."""
    captures_root: Path | None
    pr_id: str
    run_id: str
    manifest: dict | None
    manifest_run: str
    members: list[dict] = field(default_factory=list)
    dirs: dict[int, ScenarioDirEvidence] = field(default_factory=dict)
    orphans: list[int] = field(default_factory=list)
    anomalies: list[str] = field(default_factory=list)


def scenario_indices(captures_root: Path | str | None) -> list[int]:
    """Indices of the numeric directories under ``scenarios/`` (sorted)."""
    if captures_root is None:
        return []
    root = scenarios_dir(captures_root)
    try:
        entries = list(root.iterdir())
    except OSError:
        return []
    out: list[int] = []
    for entry in entries:
        if entry.is_dir() and _NUMERIC_DIR_RE.match(entry.name):
            out.append(int(entry.name))
    return sorted(out)


def _classify(captures_root: Path, index: int,
              pr_id: str, run_id: str) -> ScenarioDirEvidence:
    record = read_scenario_record(captures_root, index)
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
                               owner_pr=owner_pr, owner_run=owner_run)


def audit(captures_root: Path | str | None, *,
          pr_id: str, run_id: str = "") -> EvidenceAudit:
    """Authoritative membership for *run_id*, and every directory's claim.

    ``members`` comes from the run manifest — never from the directory
    listing.  Every ``scenarios/<n>/`` directory is classified so a caller
    can tell this run's evidence from an earlier run's, a foreign project's,
    or a legacy record with no identity at all.
    """
    if captures_root is None:
        # No captures dir at all: nothing is bound to a run, and saying so is
        # the honest answer — never audit the process's current directory.
        return EvidenceAudit(
            captures_root=None, pr_id=pr_id, run_id=run_id, manifest=None,
            manifest_run="",
            anomalies=["no captures dir — no QA evidence to audit"])
    root = Path(captures_root)
    manifest = read_manifest(captures_root, pr_id=pr_id, run_id=run_id or None)
    manifest_run = (manifest or {}).get("run_id", "")
    effective_run = run_id or manifest_run
    members = [m for m in ((manifest or {}).get("scenarios") or [])
               if isinstance(m, dict)]
    dirs = {i: _classify(root, i, pr_id, effective_run)
            for i in scenario_indices(captures_root)}
    member_indices = {m.get("index") for m in members}
    orphans = sorted(i for i in dirs if i not in member_indices)

    anomalies: list[str] = []
    if manifest is None:
        anomalies.append(
            "no qa_manifest.json — scenario membership is not run-bound")
    elif run_id and manifest_run and manifest_run != run_id:
        anomalies.append(
            f"the manifest belongs to QA run {manifest_run}, "
            f"not {run_id}")
    for i, ev in sorted(dirs.items()):
        if ev.state == FOREIGN:
            anomalies.append(
                f"scenarios/{i}: foreign record (pr_id={ev.owner_pr}) — "
                "not this PR's evidence")
        elif ev.state == UNOWNED:
            if i in member_indices:
                # The manifest says this run owns the scenario, but nothing
                # on disk carries provenance: a launched scenario that never
                # produced a verdict writes only ``prompt.md`` (and any
                # pre-fix record at that index has no identity).  Reporting
                # that as "not bound to a QA run" would contradict the
                # membership the same audit just printed.
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
            anomalies.append(
                f"scenarios/{i}: prior QA run {ev.owner_run}")
    for i in orphans:
        if dirs[i].state == CURRENT:
            anomalies.append(
                f"scenarios/{i}: not in the current run's manifest")
    for m in members:
        idx = m.get("index")
        if (isinstance(idx, int) and not isinstance(idx, bool)
                and idx not in dirs):
            # Membership without evidence: the run claims the scenario but
            # nothing is on disk — the report must not paper over it.
            anomalies.append(
                f"scenarios/{idx}: listed in the manifest but has no "
                "evidence directory — its evidence is missing")
    return EvidenceAudit(captures_root=root, pr_id=pr_id, run_id=effective_run,
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


def quarantine_foreign(captures_root: Path | str | None, *,
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
    """
    if captures_root is None:
        return []
    root = Path(captures_root)
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
