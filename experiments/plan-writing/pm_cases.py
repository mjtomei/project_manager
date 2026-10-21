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
SKIP_PREFIXES = ("<local-command-stdout>", "<local-command-stderr>", "Caveat: The messages below",
                 "[Request interrupted", "<command-message>", "<bash-input>", "<bash-stdout>", "<bash-stderr>")


def sha256_file(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def parse_map(path=MAP_PATH):
    """Rows of the inventory table: plan, evidence, [(record_path, line), ...]."""
    rows = []
    for line in path.read_text().splitlines():
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


def extract_window(records, event_line, plan, start_line=None):
    """Turns from the window start up to (not including) the event line."""
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
            if isinstance(prompt, str) and prompt.strip():
                turns.append({"line": number, "timestamp": obj.get("timestamp"), "role": "human",
                              "text": prompt.strip(), "delivery": "queued_while_working"})
    written = next((inp.get("content") for tool, _, inp in targets if tool == "Write" and inp.get("content")), None)
    return {"start_line": start_line, "event_line": event_line, "event_timestamp": event.get("timestamp"),
            "event_tools": sorted({t[0] for t in targets}), "event_matches_plan": bool(targets),
            "turns": turns, "written_content": written}


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
            excerpts = []
            for ref in located:
                records = load_records(ref["local_path"])
                key = f"{plan}:{Path(ref['local_path']).name}:{ref['line']}"
                review = windows.get(key, {})
                window = extract_window(records, ref["line"], plan, review.get("start_line"))
                draft_sha, content = None, window.pop("written_content")
                if content is not None:
                    draft_sha = hashlib.sha256(content.encode()).hexdigest()
                    (out_dir / "drafts" / f"{draft_sha}.md").write_text(content)
                excerpts.append({"record": ref["local_path"], "map_path": ref["map_path"], "record_sha256": sha256_file(ref["local_path"]),
                                 "window_reviewed": bool(review), "review_note": review.get("note"),
                                 "request_line": review.get("request_line"), "draft_sha256": draft_sha, **window})
            excerpts.sort(key=lambda e: e["event_timestamp"] or "")
            convo_path = out_dir / "conversations" / (plan.removesuffix(".md") + ".json")
            convo_path.write_text(json.dumps({"plan": plan, "excerpts": excerpts}, indent=1))
            humans = sum(1 for e in excerpts for t in e["turns"] if t["role"] == "human")
            baseline = plan_path.read_text()
            baseline_sha = hashlib.sha256(baseline.encode()).hexdigest()
            snapshot = out_dir / "baselines" / f"{baseline_sha}.md"
            snapshot.write_text(baseline)
            cases.append({
                "case_id": "pm:" + plan.removesuffix(".md"), "case_type": "pm_plan", "source": "pm-plans",
                "document_id": None, "split_group": "pm-plans",
                "inputs": {"conversation_path": str(convo_path.relative_to(out_dir.parent)),
                           "instruction": "Write the plan file this conversation asks for."},
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
                               "human_turns": humans, "needs_review": True},
            })
            entry.update({"case_id": cases[-1]["case_id"], "human_turns": humans})
        report.append(entry)
    for path in sorted(plans_dir.glob("plan-*.md")):
        if path.name not in mapped:
            report.append({"plan": path.name, "status": "not_in_map", "records": [], "plan_file_exists": True})
    return cases, report
