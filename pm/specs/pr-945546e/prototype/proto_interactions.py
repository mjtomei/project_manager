"""Scratch prototype (spec grounding only): hunk intersection + Python AST
changed-definition / new-reference detection between PR branches.

Read-only git plumbing on refs/scan/*; parses blobs with ast.parse (never
imports or executes analysed code).
"""
import os
import ast
import json
import re
import subprocess
import sys
import time
from collections import defaultdict

REPO = os.environ.get("REPO", ".")
S = sys.argv[1]
BASE = subprocess.run(["git", "rev-parse", "origin/master"], cwd=REPO,
                      capture_output=True, text=True).stdout.strip()


def git(*a):
    return subprocess.run(["git", *a], cwd=REPO, capture_output=True, text=True)


def blob(rev, path):
    r = git("show", f"{rev}:{path}")
    return r.stdout if r.returncode == 0 else None


HUNK = re.compile(r"^@@ -(\d+)(?:,(\d+))? \+(\d+)(?:,(\d+))? @@")


def hunks(a, b, path=None):
    """{path: [(old_start, old_len, new_start, new_len)]} for a..b."""
    args = ["diff", "-U0", "-M", "--no-ext-diff", "--no-textconv", a, b]
    if path:
        args += ["--", path]
    out = defaultdict(list)
    cur = None
    for line in git(*args).stdout.splitlines():
        if line.startswith("+++ "):
            p = line[4:]
            cur = p[2:] if p.startswith("b/") else None
        elif line.startswith("--- "):
            p = line[4:]
            old = p[2:] if p.startswith("a/") else None
        elif line.startswith("@@") and (cur or old):
            m = HUNK.match(line)
            if m:
                os_, ol, ns, nl = m.groups()
                out[old or cur].append((int(os_), int(ol or 1), int(ns), int(nl or 1)))
    return out


def overlap(h1, h2, ctx=3):
    hits = []
    for (s1, l1, _, _) in h1:
        for (s2, l2, _, _) in h2:
            a1, b1 = s1 - ctx, s1 + max(l1, 1) + ctx
            a2, b2 = s2 - ctx, s2 + max(l2, 1) + ctx
            if a1 <= b2 and a2 <= b1:
                hits.append(((s1, l1), (s2, l2)))
    return hits


def defs(src):
    """{qualname: (lineno, end, signature)} for module/class-level defs."""
    out = {}
    try:
        tree = ast.parse(src)
    except SyntaxError:
        return None

    def visit(body, prefix):
        for n in body:
            if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)):
                out[prefix + n.name] = (n.lineno, n.end_lineno, ast.unparse(n.args))
            elif isinstance(n, ast.ClassDef):
                out[prefix + n.name] = (n.lineno, n.end_lineno, "class")
                visit(n.body, prefix + n.name + ".")
    visit(tree.body, "")
    return out


def module_of(path):
    if not path.endswith(".py"):
        return None
    mod = path[:-3].replace("/", ".")
    return mod[:-9] if mod.endswith(".__init__") else mod


def refs(src, path, lines):
    """Resolved pm-internal references on the given new-side lines."""
    try:
        tree = ast.parse(src)
    except SyntaxError:
        return None, ["syntax-error"]
    alias = {}   # local name -> module or module:attr
    dynamic = []
    pkg = module_of(path).rsplit(".", 1)[0] if module_of(path) else ""
    for n in ast.walk(tree):
        if isinstance(n, ast.Import):
            for a in n.names:
                if a.asname:
                    alias[a.asname] = a.name
                else:
                    alias[a.name.split(".")[0]] = a.name.split(".")[0]
        elif isinstance(n, ast.ImportFrom):
            base = n.module or ""
            if n.level:
                parts = pkg.split(".")
                base = ".".join(parts[: len(parts) - n.level + 1] + ([base] if base else []))
            for a in n.names:
                if a.name == "*":
                    dynamic.append(f"star-import {base} line {n.lineno}")
                    continue
                alias[a.asname or a.name] = f"{base}:{a.name}"
        elif isinstance(n, ast.Call) and isinstance(n.func, (ast.Name, ast.Attribute)):
            fname = n.func.id if isinstance(n.func, ast.Name) else n.func.attr
            if fname in ("import_module", "__import__", "getattr") and n.lineno in lines:
                dynamic.append(f"{fname}() line {n.lineno}")
    found = []
    for n in ast.walk(tree):
        ln = getattr(n, "lineno", None)
        if ln not in lines:
            continue
        if isinstance(n, ast.Attribute) and isinstance(n.value, ast.Name):
            tgt = alias.get(n.value.id)
            if tgt and ":" not in tgt and tgt.startswith("pm_core"):
                found.append((f"{tgt}:{n.attr}", ln))
            elif tgt and ":" in tgt:
                m, a = tgt.split(":")
                found.append((f"{m}.{a}:{n.attr}", ln))  # submodule attr
        elif isinstance(n, ast.Name) and isinstance(n.ctx, ast.Load):
            tgt = alias.get(n.id)
            if tgt and ":" in tgt and tgt.startswith("pm_core"):
                found.append((tgt, ln))
    return found, dynamic


def pr_facts(pr):
    ref = f"refs/scan/{pr}"
    mb = git("merge-base", ref, BASE).stdout.strip()
    h = hunks(mb, ref)
    changed = {}
    newrefs = []
    dyn = []
    for path, hs in h.items():
        if not path.endswith(".py"):
            continue
        old = blob(mb, path)
        new = blob(ref, path)
        od = defs(old) if old else {}
        nd = defs(new) if new else {}
        if od is None or nd is None:
            dyn.append(f"{path}: syntax error")
            continue
        newlines = set()
        for (_, _, ns, nl) in hs:
            newlines.update(range(ns, ns + max(nl, 1)))
        mod = module_of(path)
        for q, (s, e, sig) in nd.items():
            if q in od and od[q][2] != sig:
                changed[f"{mod}:{q}"] = ("signature", od[q][2], sig)
            elif q in od and newlines & set(range(s, e + 1)):
                changed.setdefault(f"{mod}:{q}", ("body", None, None))
        for q in od:
            if q not in nd:
                changed[f"{mod}:{q}"] = ("removed", od[q][2], None)
        if new:
            r, d = refs(new, path, newlines)
            if r:
                newrefs += [(sym, path, ln) for sym, ln in r]
            dyn += [f"{path}: {x}" for x in (d or [])]
    return dict(mb=mb, hunks=h, changed=changed, newrefs=newrefs, dynamic=dyn)


prs = sys.argv[2].split(",")
t0 = time.monotonic()
F = {p: pr_facts(p) for p in prs}
t1 = time.monotonic()
report = {"t_facts_s": round(t1 - t0, 2), "pairs": []}
for i, a in enumerate(prs):
    for b in prs[i + 1:]:
        shared = set(F[a]["hunks"]) & set(F[b]["hunks"])
        hunk_hits = {}
        for p in shared:
            if p == "pm/project.yaml":
                continue
            ha = hunks(git("merge-base", f"refs/scan/{a}", f"refs/scan/{b}").stdout.strip(), f"refs/scan/{a}", p)[p]
            hb = hunks(git("merge-base", f"refs/scan/{a}", f"refs/scan/{b}").stdout.strip(), f"refs/scan/{b}", p)[p]
            o = overlap(ha, hb)
            if o:
                hunk_hits[p] = o[:3]
        api = []
        for x, y in ((a, b), (b, a)):
            for sym, path, ln in F[y]["newrefs"]:
                if sym in F[x]["changed"]:
                    api.append(dict(changes=x, symbol=sym, kind=F[x]["changed"][sym][0],
                                    consumer=y, at=f"{path}:{ln}"))
        report["pairs"].append(dict(a=a, b=b, shared_paths=sorted(shared),
                                    hunk_overlap=hunk_hits, api=api[:8]))
report["t_pairs_s"] = round(time.monotonic() - t1, 2)
report["changed_counts"] = {p: len(F[p]["changed"]) for p in prs}
report["dynamic"] = {p: F[p]["dynamic"][:5] for p in prs}
json.dump(report, open(f"{S}/proto.json", "w"), indent=1, default=str)
for pr in report["pairs"]:
    if pr["hunk_overlap"] or pr["api"]:
        print(pr["a"], pr["b"], "hunks:", {k: v for k, v in pr["hunk_overlap"].items()},
              "api:", pr["api"][:4])
print("times", report["t_facts_s"], report["t_pairs_s"])
print("changed", report["changed_counts"])
print("dynamic", report["dynamic"])
