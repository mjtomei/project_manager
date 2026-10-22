"""Shared presentation of the auto-start status report (no Textual imports).

``pm autostart status`` and the TUI runs popup (key ``a``) both render the
``pm.autostart.status/1`` dict through this module, so they agree on what
each row says, which PRs need a human now, and how lines wrap.

Layout is a list of *lines*; each line is a list of ``(text, role)``
segments.  Roles name what a piece of text is (``id``, ``phase``,
``attention`` …); :data:`ROLE_STYLES` maps them to Rich style strings, which
:func:`to_ansi` (CLI) and :func:`to_rich` (popup) turn into terminal
styling.  Widths are measured on the plain text in terminal cells
(``rich.cells.cell_len``), so styling never counts and wide characters do.

Per row::

    ◎ #229 pr-0b87a97 RUNNING review #3 [wait-for-merge] Support multiple
        autostart targets with CLI controls and a live TUI runs popup
        last NEEDS_WORK · ⧉ review-#229

Line 1 carries identity, state (or the human-action label), one
phase/progress token, policy labels the group does not imply, and the
title; the second part carries the compact reason and secondary details.
Both wrap onto continuation lines indented under the row.
"""

from __future__ import annotations

from rich.cells import cell_len
from rich.color import ColorSystem
from rich.style import Style

from pm_core.autostart_state import (
    ATTENTION_LABELS, blockers_text, policy_labels, status_rows,
)

# Aim: every rendered line under 100 visible columns.
MAX_WIDTH = 99
MIN_WIDTH = 30

ROLE_STYLES = {
    "header": "bold",
    "secondary": "dim",
    "sep": "dim",  # " · " between items; dropped where a line breaks
    "meta": "dim",  # one secondary label (window, run, owner): kept whole
    "id": "bold",
    "id2": "dim",
    "marker_target": "bold yellow",
    "marker_dep": "dim",
    "state_running": "green",
    "state_waiting": "yellow",
    "state_paused": "magenta",
    "state_failed": "red",
    "state_queued": "cyan",
    "state_completed": "dim green",
    # Human action needed now: conspicuous, and always with a text label.
    "attention": "bold white on red",
    "attention_text": "bold red",
    "phase": "cyan",
    "policy": "magenta",
    "exception": "bold magenta",
    "title": "",
    "reason": "",
    "notice": "bold red",
}

# Roles whose text is a single label: never broken at its inner spaces
# unless it alone is wider than the line.
_ATOMIC = {"id", "id2", "meta", "attention", "phase", "policy", "exception",
           "marker_target", "marker_dep"} | {
               r for r in ROLE_STYLES if r.startswith("state_")}

_PHASE_TOKENS = {"pending": "pending", "implementation": "impl",
                 "review": "review", "qa": "qa", "sign_off": "sign-off",
                 "merge": "merge", "done": "done"}

Seg = tuple[str, str]
Line = list[Seg]

SEP: Seg = (" · ", "sep")


def clamp_width(width: int | None) -> int:
    if not width or width <= 0:
        return MAX_WIDTH
    return max(MIN_WIDTH, min(MAX_WIDTH, int(width)))


# ---------------------------------------------------------------------------
# Wrapping
# ---------------------------------------------------------------------------

def _tokens(segs: list[Seg]) -> list[tuple[str, str, bool]]:
    """Split segments into ``(text, role, is_space)`` word/space tokens."""
    out: list[tuple[str, str, bool]] = []
    for text, role in segs:
        if not text:
            continue
        if role == "sep":
            out.append((text, role, True))
            continue
        if role in _ATOMIC:
            lead = len(text) - len(text.lstrip(" "))
            if lead:
                out.append((text[:lead], role, True))
            body = text.strip(" ")
            if body:
                out.append((body, role, False))
            trail = len(text) - len(text.rstrip(" "))
            if trail and body:
                out.append((text[len(text) - trail:], role, True))
            continue
        word = ""
        for ch in text:
            if (ch == " ") != (word[:1] == " ") and word:
                out.append((word, role, word[0] == " "))
                word = ""
            word += ch
        if word:
            out.append((word, role, word[0] == " "))
    return out


def _split_cells(text: str, width: int) -> tuple[str, str]:
    """Longest prefix of *text* fitting *width* cells (at least one char)."""
    used = 0
    for i, ch in enumerate(text):
        w = cell_len(ch)
        if used + w > width and i:
            return text[:i], text[i:]
        used += w
    return text, ""


def wrap(segs: list[Seg], width: int, indent: str) -> list[Line]:
    """Greedy word-wrap *segs* to *width* cells; continuation lines start
    with *indent* (role ``""``).  Leading spaces of *segs* are kept on the
    first line (the row's own indent); spaces and separators (role
    ``sep``) at a break are dropped — the break itself separates."""
    width = max(width, cell_len(indent) + 8)
    lines: list[Line] = [[]]
    used = 0

    def put(text: str, role: str) -> None:
        nonlocal used
        line = lines[-1]
        if line and line[-1][1] == role:
            line[-1] = (line[-1][0] + text, role)
        else:
            line.append((text, role))
        used += cell_len(text)

    def newline() -> None:
        nonlocal used
        # Drop trailing spaces from the line being closed.
        line = lines[-1]
        while line and (not line[-1][0].strip() or line[-1][1] == "sep"):
            line.pop()
        if line and line[-1][0] != line[-1][0].rstrip():
            line[-1] = (line[-1][0].rstrip(), line[-1][1])
        lines.append([])
        used = 0
        put(indent, "")

    started = False  # anything but leading space placed yet
    must_break = False  # a separator did not fit: the next item wraps
    for text, role, space in _tokens(segs):
        if space:
            if not started or used + cell_len(text) <= width:
                put(text, role)
            elif role == "sep":
                must_break = True
            continue  # a break swallows the space
        w = cell_len(text)
        if ((must_break or used + w > width) and used > cell_len(indent)
                and started):
            newline()
        must_break = False
        while used + cell_len(text) > width:
            room = width - used
            if room < cell_len(text[0]):
                newline()
                continue
            head, text = _split_cells(text, room)
            put(head, role)
            if text:
                newline()
        if text:
            put(text, role)
        started = True
    last = lines[-1]
    while last and (not last[-1][0].strip() or last[-1][1] == "sep"):
        last.pop()
    return [ln for ln in lines if ln]


# ---------------------------------------------------------------------------
# Row content
# ---------------------------------------------------------------------------

def needs_human(status: dict) -> list[dict]:
    """Runs that need a human now (``attention`` set), each PR once —
    a shared dependency is one run however many targets list it."""
    out, seen = [], set()
    for row in status_rows(status):
        run = row["run"]
        if run.get("attention") and run["pr_id"] not in seen:
            seen.add(run["pr_id"])
            out.append(run)
    return out


def state_label(run: dict) -> tuple[str, str]:
    """``(label, role)``: the human-action label if any, else the state."""
    if run.get("attention"):
        label = (run.get("attention_label")
                 or ATTENTION_LABELS.get(run["attention"])
                 or str(run["attention"]).upper())
        return label, "attention"
    state = run.get("state") or "?"
    return state.upper(), f"state_{state}"


def phase_text(row: dict) -> str:
    """One phase/progress token: progress when the phase has it, else the
    phase (omitted for completed rows, whose reason says merged/closed)."""
    run = row["run"]
    progress = row.get("progress") or ""
    if progress and run.get("attention"):
        # ``qa INPUT_REQUIRED`` next to an INPUT_REQUIRED label says it twice.
        label = state_label(run)[0]
        if progress.endswith(" " + label):
            progress = progress[:-len(label) - 1]
    if progress:
        return progress
    if run.get("state") == "completed":
        return ""
    phase = run.get("phase") or ""
    token = _PHASE_TOKENS.get(phase, phase)
    # ``QA SPEC REVIEW qa``: the label already names the phase.
    if run.get("attention") and state_label(run)[0].lower().startswith(
            token + " "):
        return ""
    return token


def display_names(status: dict) -> dict[str, str]:
    """PR id → display id for every run: how the report names a target
    holding or sharing a dependency, matching its own row (``#240``)."""
    return {r["pr_id"]: str(r.get("display_id") or r["pr_id"])
            for r in status.get("runs") or []}


def reason_text(run: dict, grouped: bool,
                names: dict[str, str] | None = None) -> str:
    """Compact reason.  Blockers name the blocking PRs and their status;
    inside a target group each blocker has its own row (with its hold
    labels), so hold causes are only spelled out in flat ``all`` mode."""
    blockers = run.get("blockers")
    if blockers:
        names = names or {}
        disp = {b["pr_id"]: b.get("display_id") or b["pr_id"]
                for b in blockers}
        return "blocked on " + blockers_text(
            blockers, holds=not grouped,
            name=lambda p: disp.get(p) or names.get(p, p))
    short = run.get("short_reason")
    return (run.get("reason") or "") if short is None else short


def row_lines(row: dict, width: int, *, grouped: bool = True,
              notice: str | None = None,
              names: dict[str, str] | None = None) -> list[Line]:
    """Wrapped lines for one status row (see module docstring).  *names*
    is :func:`display_names` of the report, for referenced targets."""
    run = row["run"]
    names = names or {}

    def name(pr_id: str) -> str:
        return names.get(pr_id, pr_id)

    indent = "  " * row["depth"]
    cont = indent + "    "
    head: list[Seg] = [(indent, "")]
    if row["kind"] == "target":
        head.append(("◎ ", "marker_target"))
    elif row["kind"] == "dep":
        head.append(("└ ", "marker_dep"))
    disp = str(run.get("display_id") or run["pr_id"])
    head.append((disp, "id"))
    if disp != run["pr_id"]:
        head += [(" ", ""), (run["pr_id"], "id2")]
    label, role = state_label(run)
    head += [(" ", ""), (label, role)]
    ph = phase_text(row)
    if ph:
        head += [(" ", ""), (ph, "phase")]
    for text, kind in policy_labels(row, name):
        head += [(" ", ""), (f"[{text}]", kind)]
    title = run.get("title") or ""
    if title:
        head += [(" ", ""), (title, "title")]
    lines = wrap(head, width, cont)

    detail: list[Seg] = []

    def add(text: str, role: str) -> None:
        if detail:
            detail.append(SEP)
        detail.append((text, role))

    reason = reason_text(run, grouped, names)
    if reason:
        add(reason, "attention_text" if run.get("attention") else "reason")
    win = run.get("window")
    if win:
        add(f"⧉ {win['name']}", "meta")
    if row.get("also"):
        add("also needed by " + ", ".join(map(name, row["also"])),
            "secondary")
    if notice:
        add(f"⚠ {notice}", "notice")
    if detail:
        lines += wrap([(cont, "")] + detail, width, cont)
    return lines


def header_lines(status: dict, width: int,
                 title: str = "Auto-start") -> list[Line]:
    """The report header: mode, target count, need-you list, run, owner."""
    mode = status.get("mode") or "off"
    segs: list[Seg] = [(f"{title}: ", "header")]
    if mode == "targets":
        n = len(status.get("targets") or [])
        segs.append((f"{n} target{'s' if n != 1 else ''}", "header"))
    elif mode == "all":
        segs.append(("all ready PRs (backlog mode)", "header"))
    else:
        segs.append(("off", "header"))
    need = needs_human(status) if mode != "off" else []
    if need:
        ids = ", ".join(str(r.get("display_id") or r["pr_id"]) for r in need)
        segs += [SEP,
                 (f"⚠ {len(need)} need{'s' if len(need) == 1 else ''} you: "
                  f"{ids}", "attention_text")]
    if status.get("run_id"):
        segs += [SEP, (f"run {status['run_id']}", "meta")]
    owner = (status.get("owner") or {}).get("session")
    if owner:
        segs += [SEP, (f"owner {owner}", "meta")]
    return wrap(segs, width, "  ")


def report_lines(status: dict, width: int = MAX_WIDTH) -> list[Line]:
    """Header + every row (the CLI text report)."""
    width = clamp_width(width)
    lines = header_lines(status, width)
    if (status.get("mode") or "off") == "off":
        lines.append([("No auto-start targets (auto-start off).", "")])
        return lines
    grouped = status.get("mode") == "targets"
    names = display_names(status)
    for row in status_rows(status):
        lines += row_lines(row, width, grouped=grouped, names=names)
    return lines


# ---------------------------------------------------------------------------
# Renderers
# ---------------------------------------------------------------------------

def plain(line: Line) -> str:
    return "".join(text for text, _ in line)


def to_ansi(lines: list[Line], color: bool = False) -> str:
    """Join lines for a terminal; without *color* the text is plain (no
    escape sequences at all)."""
    out = []
    for line in lines:
        if not color:
            out.append(plain(line))
            continue
        out.append("".join(
            Style.parse(ROLE_STYLES.get(role, "")).render(
                text, color_system=ColorSystem.STANDARD)
            for text, role in line))
    return "\n".join(out)


# The popup paints through Textual, which replaces the 16 named ANSI colours
# with its theme's RGB (Monokai: red → rgb(244,0,95), yellow → orange); in a
# 16-colour pane (pm's default TERM=screen) those round to magenta and bright
# red, so human waits stopped looking red and WAITING did.  Explicit RGB
# that rounds back to the same ANSI colour the CLI uses, at any depth.
_POPUP_RGB = {"red": "#d70000", "yellow": "#d7af00", "green": "#00af00",
              "cyan": "#00afaf", "magenta": "#af00af", "white": "#c0c0c0"}

POPUP_STYLES = {
    role: " ".join(_POPUP_RGB.get(word, word) for word in style.split())
    for role, style in ROLE_STYLES.items()}


def to_rich(line: Line, base_style: str = ""):
    """A ``rich.text.Text`` for one line (the runs popup)."""
    from rich.text import Text
    t = Text(style=base_style)
    for text, role in line:
        t.append(text, style=POPUP_STYLES.get(role, "") if role else "")
    return t
