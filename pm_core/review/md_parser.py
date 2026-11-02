"""Parsers for the markdown surfaces the walker reads.

Surfaces:
- response-block (fenced HTML comment inside `REVIEW_RESPONSE_CYCLE_N.md`)
- interaction-log (the `interactions:` list inside a response block)
- audit-doc canonical format (`CITATION_AUDIT_CYCLE_N.md`)
- response-doc (the full `REVIEW_RESPONSE_CYCLE_N.md` — preamble plus blocks)
- state-file (`STATE.md`)
- focus-file (`UI_FOCUS.md`)
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

import yaml


class _StringTimestampLoader(yaml.SafeLoader):
    """SafeLoader that keeps ISO-8601 timestamps as strings.

    The default SafeLoader converts `2026-05-20T14:32:00Z` into a
    `datetime`, which is the wrong shape for the walker's downstream
    JSON/SSE serialization and breaks round-tripping the state file.
    """


_StringTimestampLoader.add_constructor(
    "tag:yaml.org,2002:timestamp",
    lambda loader, node: loader.construct_scalar(node),
)


def _yaml_load(text: str):
    return yaml.load(text, Loader=_StringTimestampLoader)


BLOCK_OPEN_RE = re.compile(r"<!--\s*proposed-change\b[^\n]*\n", re.MULTILINE)
BLOCK_CLOSE = "-->"
# The closing fence is a line that is exactly `-->`. Matching the bare
# substring would misfire on a `-->` inside a YAML value (e.g. a research
# passage like "input --> output"), which YAML always indents under its key,
# so it never appears at column 0.
BLOCK_CLOSE_RE = re.compile(r"^-->[ \t]*$", re.MULTILINE)


@dataclass
class ResponseBlock:
    """One proposed-change block parsed out of a response doc."""

    id: str
    provenance: str  # reviewer-comment | audit-entry
    fields: dict[str, Any]  # full YAML body of the block
    span: tuple[int, int]  # (start, end) byte offsets of the full <!-- ... --> region in source

    @property
    def interactions(self) -> list[dict[str, Any]]:
        val = self.fields.get("interactions")
        return list(val) if isinstance(val, list) else []


@dataclass
class ResponseDoc:
    preamble: str
    blocks: list[ResponseBlock]


@dataclass
class AuditEntry:
    citation_header: str  # the `### ...` heading text
    cluster: str  # the enclosing `## ...` heading text
    tier: str | None
    doc_passage: str
    source_says: str
    verdict: str
    change_proposed: str
    flag: str | None
    surfaced_citations: list[str]


@dataclass
class AuditDoc:
    preamble: str
    entries: list[AuditEntry]


@dataclass
class StateFile:
    current_cycle: int | None
    current_phase: str | None
    mode: str | None
    last_transition: str | None
    raw: dict[str, Any] = field(default_factory=dict)


@dataclass
class FocusFile:
    view: str | None
    cycle: int | None
    target: str | None
    timestamp: str | None
    raw: dict[str, Any] = field(default_factory=dict)


# ---------- response blocks ----------


def parse_response_blocks(text: str) -> list[ResponseBlock]:
    """Find every `<!-- proposed-change ... -->` HTML comment and parse its YAML body."""
    blocks: list[ResponseBlock] = []
    for m in BLOCK_OPEN_RE.finditer(text):
        body_start = m.end()
        close_m = BLOCK_CLOSE_RE.search(text, body_start)
        if close_m is None:
            # No closing fence (e.g. a trailing block still being written) —
            # skip it rather than swallowing the rest of the file.
            continue
        body = text[body_start : close_m.start()]
        full_end = close_m.end()
        try:
            data = _yaml_load(body) or {}
        except yaml.YAMLError:
            continue
        if not isinstance(data, dict):
            continue
        blocks.append(
            ResponseBlock(
                id=str(data.get("id", "")),
                provenance=str(data.get("provenance", "")),
                fields=data,
                span=(m.start(), full_end),
            )
        )
    return blocks


def parse_interaction_log(block: ResponseBlock) -> list[dict[str, Any]]:
    return block.interactions


def parse_response_doc(text: str) -> ResponseDoc:
    blocks = parse_response_blocks(text)
    preamble = text[: blocks[0].span[0]] if blocks else text
    return ResponseDoc(preamble=preamble, blocks=blocks)


# ---------- audit doc ----------

_TIER_RE = re.compile(r"^\*\*Tier:\*\*\s*(.+?)\s*$", re.MULTILINE)
_VERDICT_RE = re.compile(r"^\*\*Verdict:\*\*\s*(.+?)\s*$", re.MULTILINE)
_FLAG_RE = re.compile(r"^\*\*Flag:\*\*\s*(.+?)\s*$", re.MULTILINE)
_CHANGE_LABEL_RE = re.compile(r"^\*\*Substantive change proposed:\*\*", re.MULTILINE)


def _extract_section(body: str, label: str) -> str:
    """Return the text body following `**<label>:**` up to the next `**...**:` label or end."""
    pattern = re.compile(
        rf"^\*\*{re.escape(label)}:\*\*\s*\n?(.*?)(?=^\*\*[A-Z][^*]*:\*\*|\Z)",
        re.MULTILINE | re.DOTALL,
    )
    m = pattern.search(body)
    if not m:
        return ""
    return m.group(1).strip()


def _extract_surfaced(body: str) -> list[str]:
    raw = _extract_section(body, "Surfaced citations")
    if not raw:
        return []
    out: list[str] = []
    for line in raw.splitlines():
        s = line.strip()
        if s.startswith("- "):
            out.append(s[2:].strip())
    return out


def parse_audit_doc(text: str) -> AuditDoc:
    """Parse a canonical-format `CITATION_AUDIT_CYCLE_N.md`."""
    lines = text.splitlines(keepends=True)
    # Find every `## ` cluster and `### ` entry start.
    entry_starts: list[tuple[int, str, str]] = []  # (line_index, header_text, cluster)
    cluster = ""
    preamble_end_line: int | None = None
    for i, line in enumerate(lines):
        if line.startswith("## ") and not line.startswith("### "):
            cluster = line[3:].strip()
            if preamble_end_line is None:
                preamble_end_line = i
        elif line.startswith("### "):
            if preamble_end_line is None:
                preamble_end_line = i
            entry_starts.append((i, line[4:].strip(), cluster))

    entries: list[AuditEntry] = []
    for idx, (start, header, clust) in enumerate(entry_starts):
        end = entry_starts[idx + 1][0] if idx + 1 < len(entry_starts) else len(lines)
        # Stop at the next `## ` cluster that falls before the next `### `.
        for j in range(start + 1, end):
            if lines[j].startswith("## ") and not lines[j].startswith("### "):
                end = j
                break
        body = "".join(lines[start + 1 : end])
        tier_m = _TIER_RE.search(body)
        verdict_m = _VERDICT_RE.search(body)
        flag_m = _FLAG_RE.search(body)
        # Skip an incomplete entry — the live audit-browse view reads this file
        # while the audit loop is still writing it, so the trailing entry may be
        # mid-write. The canonical field order is Tier → Doc passage → source
        # says → Verdict → Substantive change proposed → [Flag] → [Surfaced], so
        # `**Substantive change proposed:**` is the last *required* field. Gate on
        # both it and `**Verdict:**` being present (Verdict feeds a non-optional
        # field): only once the last required label has been written is the entry
        # complete. Drop it otherwise rather than surface a half-populated record.
        if verdict_m is None or _CHANGE_LABEL_RE.search(body) is None:
            continue
        entries.append(
            AuditEntry(
                citation_header=header,
                cluster=clust,
                tier=tier_m.group(1).strip() if tier_m else None,
                doc_passage=_extract_section(body, "Doc passage as currently written"),
                source_says=_extract_section(body, "What the source actually says"),
                verdict=verdict_m.group(1).strip(),
                change_proposed=_extract_section(body, "Substantive change proposed"),
                flag=flag_m.group(1).strip() if flag_m else None,
                surfaced_citations=_extract_surfaced(body),
            )
        )

    preamble = "".join(lines[: preamble_end_line or 0])
    return AuditDoc(preamble=preamble, entries=entries)


# ---------- state + focus ----------


def parse_state(text: str) -> StateFile:
    data = _yaml_load(text) or {}
    if not isinstance(data, dict):
        data = {}
    return StateFile(
        current_cycle=data.get("current-cycle"),
        current_phase=data.get("current-phase"),
        mode=data.get("mode"),
        last_transition=data.get("last-transition"),
        raw=data,
    )


def parse_focus(text: str) -> FocusFile:
    data = _yaml_load(text) or {}
    if not isinstance(data, dict):
        data = {}
    return FocusFile(
        view=data.get("view"),
        cycle=data.get("cycle"),
        target=data.get("target"),
        timestamp=data.get("timestamp"),
        raw=data,
    )
