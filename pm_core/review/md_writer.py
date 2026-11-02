"""Writers for the markdown surfaces the walker mutates.

Atomic via temp-file + `os.replace`. Concurrency-safe via `fcntl.flock`
for the read-modify-write paths (`append_interaction`, `append_note`,
`update_response_block`).
"""

from __future__ import annotations

import contextlib
import fcntl
import os
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Iterator

import yaml

from pm_core.review.md_parser import BLOCK_CLOSE, parse_response_blocks


def _utc_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _atomic_write_text(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    # Unique temp name per write: the lock-free overwrite paths (update_state,
    # update_focus) share a target, so a fixed `<name>.tmp` would let two
    # concurrent writers clobber each other's temp file before the rename. A
    # per-write temp keeps each os.replace atomic and independent.
    fd, tmp_name = tempfile.mkstemp(
        dir=str(path.parent), prefix=path.name + ".", suffix=".tmp"
    )
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(content)
            f.flush()
            # fsync before the rename so the bytes are durable, not just the
            # rename — matches the repo's atomic-write pattern
            # (pm_core.pane_registry.locked_read_modify_write).
            os.fsync(f.fileno())
        os.replace(tmp_name, path)
    except BaseException:
        with contextlib.suppress(OSError):
            os.unlink(tmp_name)
        raise


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


class _BlockDumper(yaml.SafeDumper):
    """SafeDumper that renders multi-line strings as literal `|` blocks.

    Without this, PyYAML re-serializes a `|`-style `before:`/`after:` field
    (which carries a trailing newline) as a single-quoted scalar with an
    embedded blank line — valid YAML but unreadable for the humans who
    review these files. `default_style='|'` would fix the multi-line fields
    but force every short scalar into literal style too, so we select per
    value instead.
    """


def _represent_str(dumper: yaml.Dumper, data: str):
    style = "|" if "\n" in data else None
    return dumper.represent_scalar("tag:yaml.org,2002:str", data, style=style)


def _represent_none(dumper: yaml.Dumper, _data):
    # Match the response session's convention: empty `human-verdict:` over `null`.
    return dumper.represent_scalar("tag:yaml.org,2002:null", "")


_BlockDumper.add_representer(str, _represent_str)
_BlockDumper.add_representer(type(None), _represent_none)


def _dump_block_body(data: dict[str, Any]) -> str:
    """Serialize a response-block body to YAML — pipe-block strings for multi-line."""
    return yaml.dump(
        data,
        Dumper=_BlockDumper,
        sort_keys=False,
        default_flow_style=False,
        allow_unicode=True,
        width=10_000,
    )


def _render_block(data: dict[str, Any]) -> str:
    return "<!-- proposed-change\n" + _dump_block_body(data) + BLOCK_CLOSE


# ---------- response blocks ----------


def _rewrite_block(
    path: Path, change_id: str, mutate: Callable[[dict[str, Any]], None]
) -> None:
    """Locked read-modify-write of one block's body, found by `id`.

    Reads the file, locates the block whose `id` matches `change_id`, applies
    `mutate` to a copy of its fields, then re-renders the block in place and
    writes the whole file atomically. Outside-block bytes are preserved.
    """
    path = Path(path)
    with _locked(path):
        text = path.read_text()
        blocks = parse_response_blocks(text)
        target = next((b for b in blocks if b.id == change_id), None)
        if target is None:
            raise KeyError(f"no response block with id={change_id!r}")
        merged = dict(target.fields)
        mutate(merged)
        start, end = target.span
        new_text = text[:start] + _render_block(merged) + text[end:]
        _atomic_write_text(path, new_text)


def update_response_block(
    path: Path, change_id: str, updates: dict[str, Any]
) -> None:
    """Merge `updates` into the block whose `id` matches `change_id`. Atomic."""
    _rewrite_block(path, change_id, lambda fields: fields.update(updates))


def append_interaction(
    path: Path, change_id: str, event: dict[str, Any]
) -> None:
    """Append an event to the block's `interactions:` list. Concurrency-safe."""
    event = dict(event)
    event.setdefault("at", _utc_now())

    def _append(fields: dict[str, Any]) -> None:
        existing = fields.get("interactions")
        log = list(existing) if isinstance(existing, list) else []
        log.append(event)
        fields["interactions"] = log

    _rewrite_block(path, change_id, _append)


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
        lines = text.splitlines(keepends=True)
        # Match the header by exact line, not substring: a substring check would
        # false-match a requested section that is a prefix of a longer existing
        # header (e.g. "Cit" against "## Citations"), then silently append with
        # no header of its own.
        has_section = any(line.rstrip() == header for line in lines)
        if has_section:
            # Find the next header (any `## `) after our section; insert just before it.
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
            # Keep a blank line before a following header so it stays a heading.
            tail_sep = ["\n"] if insert_at < len(lines) else []
            new_lines = lines[:j] + ["\n", entry] + tail_sep + lines[insert_at:]
            new_text = "".join(new_lines)
            if not new_text.endswith("\n"):
                new_text += "\n"
        elif text == "":
            new_text = f"{header}\n\n{entry}"
        else:
            # Ensure exactly one blank line before the new header.
            base = text if text.endswith("\n") else text + "\n"
            if not base.endswith("\n\n"):
                base += "\n"
            new_text = f"{base}{header}\n\n{entry}"
        _atomic_write_text(path, new_text)
