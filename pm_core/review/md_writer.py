"""Writers for the markdown surfaces the walker mutates.

Atomic via temp-file + `os.replace`. Concurrency-safe via `fcntl.flock`
for the read-modify-write paths (`append_interaction`, `append_note`,
`update_response_block`).
"""

from __future__ import annotations

import contextlib
import fcntl
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator

import yaml

from pm_core.review.md_parser import BLOCK_CLOSE, parse_response_blocks


def _utc_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _atomic_write_text(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(content)
    os.replace(tmp, path)


@contextlib.contextmanager
def _locked(path: Path) -> Iterator[None]:
    """Hold an exclusive flock on a sibling lockfile while the body runs."""
    path.parent.mkdir(parents=True, exist_ok=True)
    lock_path = path.with_suffix(path.suffix + ".lock")
    fd = os.open(str(lock_path), os.O_CREAT | os.O_RDWR, 0o644)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX)
        yield
    finally:
        fcntl.flock(fd, fcntl.LOCK_UN)
        os.close(fd)


def _dump_block_body(data: dict[str, Any]) -> str:
    """Serialize a response-block body to YAML — pipe-block strings for multi-line."""
    return yaml.safe_dump(
        data,
        sort_keys=False,
        default_flow_style=False,
        allow_unicode=True,
        width=10_000,
    )


def _render_block(data: dict[str, Any]) -> str:
    return "<!-- proposed-change\n" + _dump_block_body(data) + BLOCK_CLOSE


# ---------- response blocks ----------


def update_response_block(
    path: Path, change_id: str, updates: dict[str, Any]
) -> None:
    """Merge `updates` into the block whose `id` matches `change_id`. Atomic."""
    path = Path(path)
    with _locked(path):
        text = path.read_text()
        blocks = parse_response_blocks(text)
        target = next((b for b in blocks if b.id == change_id), None)
        if target is None:
            raise KeyError(f"no response block with id={change_id!r}")
        merged = dict(target.fields)
        merged.update(updates)
        new_block = _render_block(merged)
        start, end = target.span
        new_text = text[:start] + new_block + text[end:]
        _atomic_write_text(path, new_text)


def append_interaction(
    path: Path, change_id: str, event: dict[str, Any]
) -> None:
    """Append an event to the block's `interactions:` list. Concurrency-safe."""
    event = dict(event)
    event.setdefault("at", _utc_now())
    path = Path(path)
    with _locked(path):
        text = path.read_text()
        blocks = parse_response_blocks(text)
        target = next((b for b in blocks if b.id == change_id), None)
        if target is None:
            raise KeyError(f"no response block with id={change_id!r}")
        merged = dict(target.fields)
        existing = merged.get("interactions")
        log = list(existing) if isinstance(existing, list) else []
        log.append(event)
        merged["interactions"] = log
        new_block = _render_block(merged)
        start, end = target.span
        new_text = text[:start] + new_block + text[end:]
        _atomic_write_text(path, new_text)


# ---------- state + focus ----------


def _dump_yaml_doc(data: dict[str, Any]) -> str:
    return yaml.safe_dump(
        data, sort_keys=False, default_flow_style=False, allow_unicode=True
    )


def update_state(path: Path, state: dict[str, Any]) -> None:
    """Atomic write of `STATE.md`. Always stamps `last-transition` if absent."""
    path = Path(path)
    out = dict(state)
    out.setdefault("last-transition", _utc_now())
    _atomic_write_text(path, _dump_yaml_doc(out))


def update_focus(path: Path, focus: dict[str, Any]) -> None:
    """Atomic write of `UI_FOCUS.md`. Always stamps `timestamp` last."""
    path = Path(path)
    out = {k: v for k, v in focus.items() if k != "timestamp"}
    out["timestamp"] = focus.get("timestamp") or _utc_now()
    _atomic_write_text(path, _dump_yaml_doc(out))


# ---------- notes ----------


def append_note(
    path: Path,
    section: str,
    body: str,
    *,
    timestamp: str | None = None,
) -> None:
    """Append a timestamped entry to `## <section>` in `NOTES.md`.

    Creates the file and/or the section if missing. Concurrency-safe.
    """
    path = Path(path)
    ts = timestamp or _utc_now()
    entry = f"[{ts}]\n{body.rstrip()}\n"
    with _locked(path):
        text = path.read_text() if path.exists() else ""
        header = f"## {section}"
        if header in text:
            # Find the next header (any `## `) after our section; insert just before it.
            lines = text.splitlines(keepends=True)
            in_section = False
            insert_at = len(lines)
            for i, line in enumerate(lines):
                if line.rstrip() == header:
                    in_section = True
                    continue
                if in_section and line.startswith("## "):
                    insert_at = i
                    break
            # Trim trailing blanks within the section so the new entry sits cleanly.
            j = insert_at
            while j > 0 and lines[j - 1].strip() == "":
                j -= 1
            new_lines = lines[:j] + ["\n", entry] + lines[insert_at:]
            new_text = "".join(new_lines)
            if not new_text.endswith("\n"):
                new_text += "\n"
        else:
            sep = "" if text == "" or text.endswith("\n") else "\n"
            new_text = f"{text}{sep}{header}\n\n{entry}"
        _atomic_write_text(path, new_text)
