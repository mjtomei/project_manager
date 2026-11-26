"""Replay the proposed counting rule over real QA history (spec tooling only).

    python3 pm/specs/pr-b491378/tools/trace_registry.py [pm/project.yaml]

Uses the `QA <VERDICT>:` notes that pm_core/tui/qa_loop_ui.py:_record_qa_note
writes once per processed run.  They are the only durable per-run history
today (no run list exists), so this is an approximation:

* a note's verdict is the run's aggregate verdict; the QA workdir suffix
  (`.../qa/<pr>-<loop_id>`) is the run identity when present;
* stopped/superseded runs cannot be told apart in old notes (the proposal
  records that explicitly; see impl.md R2), so every NEEDS_WORK note counts;
* CLI-driven runs (`pm pr qa-run-bg`) wrote no note and are missing.

Prints, per PR with any QA note, the verdict sequence and where a checkpoint
would become due at thresholds 1, 2 and 3, assuming each checkpoint completes
before the next QA run.  Writes nothing.
"""
import re
import sys
from collections import Counter

import yaml

try:
    from yaml import CSafeLoader as Loader
except ImportError:  # pragma: no cover
    from yaml import SafeLoader as Loader

NOTE_RE = re.compile(r"^QA (PASS|NEEDS_WORK|INPUT_REQUIRED|ERROR):")
RUN_RE = re.compile(r"\(workdir: [^)]*/qa/[^/)]*-([0-9a-f]{16})\)")
SHOW = ("pr-f38005f", "pr-8e693f6", "pr-2d5f712", "pr-5e96046", "pr-88fdba1",
        "pr-0b827df", "pr-6be8ee6")


def runs_for(pr):
    seen, out = set(), []
    for n in sorted(pr.get("notes") or [], key=lambda n: str(n.get("created_at") or "")):
        t = n.get("text") or ""
        m = NOTE_RE.match(t)
        if not m:
            continue
        r = RUN_RE.search(t)
        key = (m.group(1), r.group(1) if r else n.get("id"))
        if key in seen:          # same verdict for the same run: one record
            continue
        seen.add(key)
        out.append((str(n.get("created_at"))[:16], m.group(1),
                    r.group(1) if r else "-", n.get("id")))
    return out


def due_points(seq, threshold):
    count, due = 0, []
    for i, (_, verdict, _, _) in enumerate(seq):
        if verdict == "NEEDS_WORK":
            count += 1
            if threshold and count >= threshold:
                due.append(i)
                count = 0       # checkpoint completes before the next run
    return due


def main(path):
    data = yaml.load(open(path), Loader=Loader)
    totals = Counter()
    for pr in data["prs"]:
        seq = runs_for(pr)
        if not seq:
            continue
        totals["prs"] += 1
        totals["runs"] += len(seq)
        totals["nw"] += sum(1 for s in seq if s[1] == "NEEDS_WORK")
        for t in (1, 2, 3):
            totals[f"t{t}"] += len(due_points(seq, t))
            totals[f"prs_t{t}"] += bool(due_points(seq, t))
        if pr["id"] in SHOW:
            print(f"\n{pr['id']} [{pr.get('status')}] {pr.get('title', '')[:70]}")
            d2, d3 = set(due_points(seq, 2)), set(due_points(seq, 3))
            for i, (at, v, run, nid) in enumerate(seq):
                mark = []
                if i in d2:
                    mark.append("due@2")
                if i in d3:
                    mark.append("due@3")
                print(f"  {at}  {v:<14} run {run:<16} {nid}  {' '.join(mark)}")
    print("\nRegistry totals (QA-noted runs only):")
    print(f"  PRs with QA notes: {totals['prs']}; runs: {totals['runs']}; "
          f"NEEDS_WORK runs: {totals['nw']}")
    for t in (1, 2, 3):
        print(f"  threshold {t}: {totals[f't{t}']} checkpoints across "
              f"{totals[f'prs_t{t}']} PRs")


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else "pm/project.yaml")
