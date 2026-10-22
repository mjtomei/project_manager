"""Recover PM planning conversations as natural-prompt cases.

Reads the plan-to-session map (pm/docs/plan-session-sources-2026-10-19.md),
opens each referenced conversation record, and extracts the conversation that
precedes the mapped write/edit event: human turns, assistant replies, and pm
injected prompts kept as separate roles. Tool calls and tool results are left
out. The current plan file is attached as the production baseline, not as a
known-good reference, and is snapshotted at build time (plan files keep
changing on master); the content written at the event is kept when the event
is a Write. Paths the catalog records under out_dir are relative to its parent
(the data directory), like the corpus text paths, so a copied data/ still
resolves.

Files the human or the pm prompt named, and earlier versions of the plan
itself, enter the excerpt as `source_file` turns: the Read results the session
saw, at the point it read them, with path, hash and line range. Nothing is
substituted from the current tree or the finished plan; a named file the
window never read, a failed read, an edit whose earlier version was not read
in full, or a snapshot identical to the baseline is listed in `source_gaps`.

The map identifies candidate provenance, not assent, so every case is marked
`needs_review`; reviewed windows live in pm_case_windows.json. Plans whose
records are missing, unmounted or never located are reported, not invented.
"""

import hashlib
import json
import os
import re
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parent.parent
MAP_PATH = REPO / "pm" / "docs" / "plan-session-sources-2026-10-19.md"
PLANS = REPO / "pm" / "plans"
WINDOWS = HERE / "pm_case_windows.json"
MAP_PREFIXES = {"/home/matt/.claude/projects": "claude_projects", "/home/matt/.codex": "codex_home"}
RECORD_REF = re.compile(r"`(/home/matt/[^`]+?\.jsonl):(\d+)`")
PLAN_WRITE_TOOLS = {"Write", "Edit", "MultiEdit", "NotebookEdit"}
INJECTED_MARKERS = ("## Session Context", "You're working on PR", "This session is managed by `pm`",
                    "You are running inside a pm", "## Task\n", "<command-name>", "<local-command")
PATH_TOKEN = re.compile(r"[\w./~-]*/[\w.-]+\.(?:md|txt|yaml|yml|py|json|rst)\b")
EXAMPLES = re.compile(r"\(e\.g\.[^)]*\)", re.S)  # the pm prompt's example paths are not requests
EDIT_STATUSES = ("edits_only", "revision_only")
INSTRUCTION = "Write the plan file this conversation asks for."
SOURCE_NOTE = (" Files the session read are included as `source_file` turns, as the session saw them when it read them"
               " (a line range marks a partial read).")
SKIP_PREFIXES = ("<local-command-stdout>", "<local-command-stderr>", "Caveat: The messages below",
                 "[Request interrupted", "<command-message>", "<bash-input>", "<bash-stdout>", "<bash-stderr>",
                 "<task-notification>")


def sha256_file(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def parse_map(path=MAP_PATH):
    """Rows of the inventory table: plan, evidence, [(record_path, line), ...]."""
    rows = []
    for line in path.read_text(encoding="utf-8").splitlines():
        m = re.match(r"^\|\s*(plan-[\w.-]+\.md)\s*\|\s*([^|]+?)\s*\|\s*(.*?)\s*\|\s*$", line)
        if m:
            refs = [(p, int(n)) for p, n in RECORD_REF.findall(m.group(3))]
            note = re.sub(r"`[^`]+`(<br>)?", "", m.group(3)).strip(" —-")
            rows.append({"plan": m.group(1), "evidence": m.group(2), "records": refs, "note": note})
    return rows


def translate(record_path, roots):
    """Map the inventory's host path onto locally mounted history roots."""
    for prefix, key in MAP_PREFIXES.items():
        if record_path.startswith(prefix):
            root = roots.get(key)
            return (Path(root) / record_path[len(prefix):].lstrip("/")) if root else None
    return None


def resolve_record(rec, roots=None):
    """Local path of a catalogued conversation record, re-translated when its stored path is gone.

    Stored paths are absolute under the history root mounted at build time
    ($HOME/.claude/projects or PM_CLAUDE_PROJECTS); another environment may
    mount the same histories elsewhere.
    """
    path = Path(rec["path"])
    if path.exists():
        return path
    return translate(rec["map_path"], roots or default_roots()) or path


def default_roots():
    home = Path(os.environ.get("HOME", "~")).expanduser()
    return {"claude_projects": os.environ.get("PM_CLAUDE_PROJECTS", str(home / ".claude" / "projects")),
            "codex_home": os.environ.get("PM_CODEX_HOME") or (str(home / ".codex") if (home / ".codex").exists() else None)}


def _text_blocks(content):
    if isinstance(content, str):
        return [content]
    return [b.get("text", "") for b in content or [] if isinstance(b, dict) and b.get("type") == "text"]


def _plan_targets(obj):
    """Plan files touched by tool calls in an assistant record."""
    out = []
    content = (obj.get("message") or {}).get("content")
    for block in content if isinstance(content, list) else []:
        if not isinstance(block, dict) or block.get("type") != "tool_use":
            continue
        inp = block.get("input") or {}
        path = inp.get("file_path") or inp.get("notebook_path") or ""
        if block.get("name") in PLAN_WRITE_TOOLS and "/pm/plans/" in path:
            out.append((block["name"], Path(path).name, inp))
        elif block.get("name") == "Bash":
            out.extend(("Bash", name, inp) for name in re.findall(r"pm/plans/(plan-[\w.-]+\.md)", inp.get("command", "")))
    return out


def classify_user(obj):
    """Role of a user-type record's text: human, injected, or None to skip."""
    if obj.get("isMeta") or obj.get("isCompactSummary") or obj.get("toolUseResult") is not None:
        return None
    if (obj.get("origin") or {}).get("kind", "human") != "human":
        return None  # background-task notifications and other sessions' messages: nobody typed them
    content = (obj.get("message") or {}).get("content")
    if isinstance(content, list) and any(isinstance(b, dict) and b.get("type") == "tool_result" for b in content):
        return None
    text = "\n".join(_text_blocks(content)).strip()
    if not text or text.startswith(SKIP_PREFIXES) or re.fullmatch(r"(?s)\s*<system-reminder>.*</system-reminder>\s*", text):
        return None
    if any(text.startswith(m) or m in text[:400] for m in INJECTED_MARKERS):
        return "injected"
    return "human"


def load_records(path):
    out = []
    with open(path, encoding="utf-8", errors="replace") as handle:
        for number, line in enumerate(handle, 1):
            try:
                out.append((number, json.loads(line)))
            except json.JSONDecodeError:
                out.append((number, {}))
    return out


def named_paths(turns):
    """Paths named in human and injected turns, in order of first mention."""
    out = []
    for t in turns:
        if t["role"] in ("human", "injected"):
            out += [p for p in PATH_TOKEN.findall(EXAMPLES.sub("", t["text"])) if p not in out]
    return out


def path_matches(path, token):
    """True when a read file path is the path a turn named (absolute, or relative to some root)."""
    rel = token.lstrip("~").lstrip("/")
    return path == token or path.endswith("/" + rel)


def is_plan_path(path, plan):
    return Path(path).name == plan and "/plans/" in path


def _read_results(window_records):
    """Read tool results in a window: (snapshots, failed reads, shell commands)."""
    calls, snapshots, failures, shell = {}, [], [], []
    for number, obj in window_records:
        content = (obj.get("message") or {}).get("content")
        for block in content if isinstance(content, list) else []:
            if not isinstance(block, dict):
                continue
            if block.get("type") == "tool_use" and block.get("name") == "Read" and block.get("id"):
                calls[block.get("id")] = (number, (block.get("input") or {}).get("file_path") or "")
            elif block.get("type") == "tool_use" and block.get("name") == "Bash":
                shell.append((block.get("input") or {}).get("command") or "")
            elif block.get("type") == "tool_result" and block.get("tool_use_id") in calls:
                call_line, path = calls[block["tool_use_id"]]
                result = obj.get("toolUseResult")
                f = result.get("file") if isinstance(result, dict) and result.get("type") == "text" else None
                if isinstance(f, dict) and isinstance(f.get("content"), str):
                    total, count = f.get("totalLines"), f.get("numLines")
                    snapshots.append({"line": number, "timestamp": obj.get("timestamp"), "read_call_line": call_line,
                                      "path": f.get("filePath") or path, "text": f["content"],
                                      "lines": {"start": f.get("startLine"), "count": count, "total": total},
                                      "partial": not (f.get("startLine") in (1, None) and count == total)})
                else:
                    error = result if isinstance(result, str) else json.dumps(block.get("content"))[:200]
                    failures.append({"line": number, "path": path, "error": str(error)[:200]})
    return snapshots, failures, shell


def source_turns(window_records, turns, plan):
    """Read snapshots of named files and of the plan itself, plus gaps for named files the window lacks."""
    snapshots, failures, shell = _read_results(window_records)
    named = [t for t in named_paths(turns) if not is_plan_path(t, plan)]
    out, seen = [], set()
    for snap in snapshots:
        if is_plan_path(snap["path"], plan):
            relation = "plan_earlier_version"
        elif any(path_matches(snap["path"], t) for t in named):
            relation = "named_source"
        else:
            continue  # the session's own exploration: not part of the request
        sha = hashlib.sha256(snap["text"].encode()).hexdigest()
        if (snap["path"], sha) in seen:
            continue  # re-read of identical content
        seen.add((snap["path"], sha))
        out.append({**snap, "role": "source_file", "relation": relation, "sha256": sha})
    gaps = []
    for token in named:
        if any(path_matches(s["path"], token) for s in out):
            continue
        reason = "named but not read with the Read tool in the window"
        failed = [f["error"] for f in failures if path_matches(f["path"], token)]
        if failed:
            reason += "; read failed: " + failed[0]
        if any(Path(token).name in cmd for cmd in shell):
            reason += "; mentioned in a shell command (output is not a file snapshot)"
        gaps.append({"path": token, "reason": reason})
    return out, gaps


def extract_window(records, event_line, plan, start_line=None):
    """Turns from the window start up to (not including) the event line, with source-file snapshots."""
    event = dict(records[event_line - 1][1]) if 0 < event_line <= len(records) else {}
    targets = [t for t in _plan_targets(event) if t[1] == plan]
    if start_line is None:
        start_line = 1
        for number, obj in reversed(records[: event_line - 1]):
            if obj.get("type") == "assistant" and any(name != plan for _, name, _ in _plan_targets(obj)):
                start_line = number + 1
                break
    turns = []
    for number, obj in records[start_line - 1: event_line - 1]:
        kind = obj.get("type")
        if kind == "user":
            role = classify_user(obj)
            if role:
                turns.append({"line": number, "timestamp": obj.get("timestamp"), "role": role,
                              "text": "\n".join(_text_blocks(obj["message"]["content"])).strip()})
        elif kind == "assistant":
            text = "\n".join(_text_blocks((obj.get("message") or {}).get("content"))).strip()
            if text:
                turns.append({"line": number, "timestamp": obj.get("timestamp"), "role": "assistant", "text": text})
        elif kind == "attachment" and (obj.get("attachment") or {}).get("type") == "queued_command":
            prompt = obj["attachment"].get("prompt")
            if (obj["attachment"].get("commandMode", "prompt") == "prompt" and isinstance(prompt, str) and prompt.strip()
                    and not prompt.lstrip().startswith(SKIP_PREFIXES)):
                turns.append({"line": number, "timestamp": obj.get("timestamp"), "role": "human",
                              "text": prompt.strip(), "delivery": "queued_while_working"})
    sources, gaps = source_turns(records[start_line - 1: event_line - 1], turns, plan)
    turns = sorted(turns + sources, key=lambda t: t["line"])
    written = next((inp.get("content") for tool, _, inp in targets if tool == "Write" and inp.get("content")), None)
    return {"start_line": start_line, "event_line": event_line, "event_timestamp": event.get("timestamp"),
            "event_tools": sorted({t[0] for t in targets}), "event_matches_plan": bool(targets),
            "turns": turns, "source_gaps": gaps, "written_content": written}


def substantive_plan(text):
    """True for an earlier plan version with content, not pm's empty template (title and a comment)."""
    body = re.sub(r"<!--.*?-->", "", text, flags=re.S)
    return len(re.sub(r"(?m)^#.*$", "", body).split()) > 20


def task_kind(status, reviews, turns):
    """new, edit, or a reviewed override such as reformat (the plan restates a document the session read).

    A session that read an earlier version of the plan with content revised it, whatever the map says.
    """
    override = next((r["task_kind"] for r in reviews if r.get("task_kind")), None)
    revised = any(t["role"] == "source_file" and t["relation"] == "plan_earlier_version" and substantive_plan(t["text"])
                  for t in turns)
    return override or ("edit" if status in EDIT_STATUSES or revised else "new")


def status_for(row, located):
    evidence = row["evidence"].lower()
    if not row["records"]:
        return "not_located"
    if not located:
        return "history_not_mounted"
    if "edits only" in evidence:
        return "edits_only"
    if "revision" in evidence:
        return "revision_only"
    return "recovered"


def finalize_sources(excerpts, plan, status, reviews, baseline_sha):
    """Withhold snapshots equal to the baseline, classify the task, and collect gaps; returns (kind, sources, gaps).

    Mutates the excerpts' turns and source_gaps, so it runs before they are written.
    """
    for e in excerpts:
        # a snapshot equal to the finished plan would hand the generator its reference
        for t in [t for t in e["turns"] if t.get("sha256") == baseline_sha]:
            e["turns"].remove(t)
            e["source_gaps"].append({"path": t["path"], "reason": "snapshot identical to the production baseline; withheld"})
    kind = task_kind(status, reviews, [t for e in excerpts for t in e["turns"]])
    gaps = []
    for e in excerpts:
        if kind == "edit" and not any(t["role"] == "source_file" and t["relation"] == "plan_earlier_version"
                                      and not t["partial"] for t in e["turns"]):
            e["source_gaps"].append({"path": plan, "reason": "earlier plan version not read in full in the window"})
        for g in e["source_gaps"]:
            g = {**g, "event_line": e["event_line"], "record": e["map_path"]}
            gaps += [g] if g not in gaps else []
    sources = [{"path": t["path"], "relation": t["relation"], "sha256": t["sha256"], "record_line": t["line"],
                "read_at": t["timestamp"], "lines": t["lines"], "partial": t["partial"]}
               for e in excerpts for t in e["turns"] if t["role"] == "source_file"]
    return kind, sources, gaps


def build(out_dir, roots=None, map_path=None, plans_dir=None, windows_path=None):
    """Write conversation excerpts and return (cases, plan_report)."""
    roots = roots or default_roots()
    map_path, plans_dir = Path(map_path or MAP_PATH), Path(plans_dir or PLANS)
    windows_path = Path(windows_path or WINDOWS)
    windows = json.loads(windows_path.read_text()) if windows_path.exists() else {}
    windows.pop("_about", None)
    out_dir = Path(out_dir)
    for sub in ("conversations", "drafts", "baselines"):
        (out_dir / sub).mkdir(parents=True, exist_ok=True)
    rows = parse_map(map_path)
    mapped = {r["plan"] for r in rows}
    cases, report = [], []
    for row in rows:
        plan = row["plan"]
        plan_path = plans_dir / plan
        refs = []
        for record, line in row["records"]:
            local = translate(record, roots)
            refs.append({"map_path": record, "line": line, "local_path": str(local) if local else None,
                         "exists": bool(local and local.exists())})
        located = [r for r in refs if r["exists"]]
        status = status_for(row, located)
        entry = {"plan": plan, "map_evidence": row["evidence"], "status": status, "records": refs,
                 "plan_file_exists": plan_path.exists(), "map_note": row["note"]}
        if status in ("recovered", "edits_only", "revision_only") and plan_path.exists():
            excerpts, reviews = [], []
            for ref in located:
                records = load_records(ref["local_path"])
                key = f"{plan}:{Path(ref['local_path']).name}:{ref['line']}"
                review = windows.get(key, {})
                reviews.append(review)
                window = extract_window(records, ref["line"], plan, review.get("start_line"))
                draft_sha, content = None, window.pop("written_content")
                if content is not None:
                    draft_sha = hashlib.sha256(content.encode()).hexdigest()
                    (out_dir / "drafts" / f"{draft_sha}.md").write_text(content, encoding="utf-8")
                excerpts.append({"record": ref["local_path"], "map_path": ref["map_path"], "record_sha256": sha256_file(ref["local_path"]),
                                 "window_reviewed": bool(review), "review_note": review.get("note"),
                                 "request_line": review.get("request_line"), "draft_sha256": draft_sha, **window})
            excerpts.sort(key=lambda e: e["event_timestamp"] or "")
            baseline = plan_path.read_text(encoding="utf-8")
            baseline_sha = hashlib.sha256(baseline.encode()).hexdigest()
            kind, sources, gaps = finalize_sources(excerpts, plan, status, reviews, baseline_sha)
            convo_path = out_dir / "conversations" / (plan.removesuffix(".md") + ".json")
            convo = json.dumps({"plan": plan, "excerpts": excerpts}, indent=1)
            convo_path.write_text(convo, encoding="utf-8")
            humans = sum(1 for e in excerpts for t in e["turns"] if t["role"] == "human")
            fidelity = ({"applicable": False, "reason": "reformat of a source document" if kind == "reformat" else "no human turns"}
                        if kind == "reformat" or not humans else {"applicable": True})
            snapshot = out_dir / "baselines" / f"{baseline_sha}.md"
            snapshot.write_text(baseline, encoding="utf-8")
            cases.append({
                "case_id": "pm:" + plan.removesuffix(".md"), "case_type": "pm_plan", "source": "pm-plans",
                "document_id": None, "split_group": "pm-plans",
                "inputs": {"conversation_path": str(convo_path.relative_to(out_dir.parent)),
                           "conversation_sha256": hashlib.sha256(convo.encode()).hexdigest(),
                           "instruction": INSTRUCTION + (SOURCE_NOTE if sources else "")},
                "task_kind": kind,
                "baseline": {"path": str(plan_path.relative_to(REPO)) if plan_path.is_relative_to(REPO) else str(plan_path),
                             "snapshot": str(snapshot.relative_to(out_dir.parent)), "sha256": baseline_sha,
                             "words": len(baseline.split()), "role": "production_baseline (not a known-good reference)"},
                "provenance": {"map": str(map_path.relative_to(REPO)) if map_path.is_relative_to(REPO) else str(map_path),
                               "map_evidence": row["evidence"], "history_kind": status,
                               "records": [{"path": e["record"], "map_path": e["map_path"], "event_line": e["event_line"],
                                            "start_line": e["start_line"], "event_tools": e["event_tools"],
                                            "event_matches_plan": e["event_matches_plan"], "record_sha256": e["record_sha256"],
                                            "window_reviewed": e["window_reviewed"], "request_line": e["request_line"],
                                            "review_note": e["review_note"], "draft_sha256": e["draft_sha256"]} for e in excerpts],
                               "missing_records": [r for r in refs if not r["exists"]],
                               "source_files": sources, "source_gaps": gaps, "human_turn_fidelity": fidelity,
                               "human_turns": humans, "needs_review": True},
            })
            entry.update({"case_id": cases[-1]["case_id"], "human_turns": humans, "task_kind": kind,
                          "human_turn_fidelity": fidelity["applicable"], "source_files": len(sources), "source_gaps": gaps})
        report.append(entry)
    for path in sorted(plans_dir.glob("plan-*.md")):
        if path.name not in mapped:
            report.append({"plan": path.name, "status": "not_in_map", "records": [], "plan_file_exists": True})
    return cases, report
