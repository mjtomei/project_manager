"""Scratch measurement: changed paths per active PR branch vs origin/master.

Read-only: uses rev-parse / merge-base / diff on refs/scan/* only.
"""
import os
import json
import subprocess
import sys
import time
from collections import defaultdict
from itertools import combinations

REPO = os.environ.get("REPO", ".")
S = sys.argv[1]
BASE = "origin/master"


def git(*a):
    return subprocess.run(["git", *a], cwd=REPO, capture_output=True, text=True)


rows = [l.split() for l in open(f"{S}/active_remote.txt")]
t0 = time.monotonic()
base = git("rev-parse", BASE).stdout.strip()
info = {}
for branch, pr, status, plan, sha in rows:
    ref = f"refs/scan/{pr}"
    contained = git("merge-base", "--is-ancestor", ref, base).returncode == 0
    mb = git("merge-base", ref, base).stdout.strip()
    files = []
    if mb and not contained:
        r = git("diff", "--name-status", "-M", mb, ref)
        for line in r.stdout.splitlines():
            parts = line.split("\t")
            if parts[0].startswith("R"):
                files.append(parts[2])
                files.append(parts[1])
            else:
                files.append(parts[-1])
    behind = int(git("rev-list", "--count", f"{mb}..{base}").stdout.strip() or 0) if mb else None
    info[pr] = dict(status=status, plan=plan, sha=sha, contained=contained,
                    mb=mb, behind=behind, files=sorted(set(files)))
t1 = time.monotonic()

REG = {"pm/project.yaml"}
by_file = defaultdict(set)
for pr, d in info.items():
    for f in d["files"]:
        if f in REG or f.startswith("pm/specs/"):
            continue
        by_file[f].add(pr)
pairs = defaultdict(set)
for f, prs in by_file.items():
    for a, b in combinations(sorted(prs), 2):
        pairs[(a, b)].add(f)
t2 = time.monotonic()

cross = {k: v for k, v in pairs.items() if info[k[0]]["plan"] != info[k[1]]["plan"]}
out = {
    "base": base,
    "n_prs": len(info),
    "contained": [p for p, d in info.items() if d["contained"]],
    "n_pairs_overlap": len(pairs),
    "n_cross_plan_pairs": len(cross),
    "t_git_facts_s": round(t1 - t0, 2),
    "t_pairs_s": round(t2 - t1, 3),
    "reg_only_prs": [p for p, d in info.items() if d["files"] and set(d["files"]) <= (REG | {f for f in d["files"] if f.startswith("pm/")})],
}
json.dump({"summary": out, "info": info,
           "pairs": {f"{a}|{b}": sorted(v) for (a, b), v in pairs.items()}},
          open(f"{S}/scan.json", "w"), indent=1)
print(json.dumps(out, indent=1))
