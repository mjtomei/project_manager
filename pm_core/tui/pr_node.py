"""Individual PR node widget for the tech tree."""

from textual.widget import Widget
from rich.text import Text
from rich.cells import cell_len
from rich.console import RenderableType


STATUS_ICONS = {
    "pending": "○",
    "in_progress": "◎",
    "in_review": "◉",
    "qa": "●",
    "merged": "✓",
    "closed": "✗",
    "blocked": "✗",
}

VERDICT_MARKERS = {
    "PASS": "✓",
    "PASS_WITH_SUGGESTIONS": "~",
    "NEEDS_WORK": "✗",
    "KILLED": "☠",
    "TIMEOUT": "⏱",
    "ERROR": "!",
    "INPUT_REQUIRED": "⏸",
}

VERDICT_STYLES = {
    "PASS": "bold green",
    "PASS_WITH_SUGGESTIONS": "bold yellow",
    "NEEDS_WORK": "bold red",
    "KILLED": "bold red",
    "TIMEOUT": "bold red",
    "ERROR": "bold red",
    "INPUT_REQUIRED": "bold red",
}

SPINNER_FRAMES = "◐◓◑◒"

STATUS_STYLES = {
    "pending": "white",
    "in_progress": "bold yellow",
    "in_review": "bold cyan",
    "qa": "bold magenta",
    "merged": "bold green",
    "closed": "dim red",
    "blocked": "bold red",
}

STATUS_BG = {
    "pending": "",
    "in_progress": "on #333300",
    "in_review": "on #003333",
    "qa": "on #330033",
    "merged": "on #003300",
    "closed": "on #220000",
    "blocked": "on #330000",
}

STATUS_FILTER_CYCLE = [None, "pending", "in_progress", "in_review", "qa", "merged", "closed"]

NODE_W = 24
NODE_H = 5
H_GAP = 6
V_GAP = 2


class PRNode(Widget):
    """Individual PR node widget with absolute positioning."""

    DEFAULT_CSS = """
    PRNode {
        width: 24;
        height: 5;
    }
    """

    def __init__(self, pr: dict, **kwargs):
        super().__init__(**kwargs)
        self._pr = pr
        self._is_selected = False
        self._anim_frame = 0
        self._is_auto_target = False
        self._has_spinner = False  # True if this node needs animation

    @property
    def pr_id(self) -> str:
        return self._pr["id"]

    def update_pr(self, pr: dict) -> None:
        """Update PR data and refresh if changed."""
        if pr != self._pr:
            self._pr = pr
            self.refresh()

    def set_selected(self, selected: bool) -> None:
        if self._is_selected != selected:
            self._is_selected = selected
            self.refresh()

    def set_auto_target(self, is_target: bool) -> None:
        if self._is_auto_target != is_target:
            self._is_auto_target = is_target
            self.refresh()

    def advance_animation(self) -> None:
        """Advance spinner frame. Only refreshes if this node has a spinner."""
        self._anim_frame = (self._anim_frame + 1) % len(SPINNER_FRAMES)
        if self._has_spinner:
            self.refresh()

    def _get_loop_marker(self) -> tuple[str, str]:
        """Return (marker_text, marker_style) for review loop or merge state."""
        pr_id = self._pr["id"]
        try:
            loops = self.app._review_loops
            state = loops.get(pr_id)
            if state:
                if state.running:
                    spinner = SPINNER_FRAMES[self._anim_frame % len(SPINNER_FRAMES)]
                    if state.input_required:
                        return (f"⏸{state.iteration}{spinner}", "bold red")
                    if state.stop_requested:
                        return (f"⏹{state.iteration}{spinner}", "bold red")
                    return (f"⟳{state.iteration}{spinner}", "bold cyan")
                if state.latest_verdict:
                    v = state.latest_verdict
                    marker = VERDICT_MARKERS.get(v, v[:4])
                    style = VERDICT_STYLES.get(v, "")
                    return (f"⟳{state.iteration}{marker}", style)
            merge_input = getattr(self.app, '_merge_input_required_prs', set())
            if pr_id in merge_input:
                spinner = SPINNER_FRAMES[self._anim_frame % len(SPINNER_FRAMES)]
                return (f"⏸M{spinner}", "bold red")
        except Exception:
            pass
        return ("", "")

    def render(self) -> RenderableType:
        pr = self._pr
        status = pr.get("status", "pending")
        icon = STATUS_ICONS.get(status, "?")
        node_style = STATUS_STYLES.get(status, "white")
        bg_style = STATUS_BG.get(status, "")

        if self._is_selected:
            top = "╔" + "═" * (NODE_W - 2) + "╗"
            bot = "╚" + "═" * (NODE_W - 2) + "╝"
            side = "║"
        else:
            top = "┌" + "─" * (NODE_W - 2) + "┐"
            bot = "└" + "─" * (NODE_W - 2) + "┘"
            side = "│"

        display_id = f"#{pr.get('gh_pr_number')}" if pr.get("gh_pr_number") else pr["id"]
        max_id_len = NODE_W - 4
        if self._is_auto_target:
            truncated_id = display_id[:max_id_len - 2]
            id_content = f"{truncated_id} ◎"
        else:
            id_content = display_id[:max_id_len]
        id_line = f"{side} {id_content:<{max_id_len}} {side}"

        title = pr.get("title", "???")
        max_title_len = NODE_W - 4
        if len(title) > max_title_len:
            title = title[:max_title_len - 1] + "…"
        title_line = f"{side} {title:<{NODE_W - 4}} {side}"

        status_text = f"{icon} {status}"
        loop_marker, loop_style = self._get_loop_marker()

        has_spinner = False
        if loop_marker:
            status_text += f" {loop_marker}"
            # Check if the loop marker contains a spinner character
            if any(c in loop_marker for c in SPINNER_FRAMES):
                has_spinner = True
        else:
            if status in ("in_progress", "in_review") and pr.get("workdir"):
                try:
                    tracker = self.app._pane_idle_tracker
                    if tracker.is_tracked(pr["id"]) and not tracker.is_idle(pr["id"]):
                        spinner = SPINNER_FRAMES[self._anim_frame % len(SPINNER_FRAMES)]
                        loop_style = "bold cyan"
                        status_text += f" {spinner}"
                        has_spinner = True
                except Exception:
                    pass

        self._has_spinner = has_spinner

        machine = pr.get("agent_machine")
        if machine:
            avail = NODE_W - 4 - cell_len(status_text) - 1
            if avail > 3:
                status_text += f" {machine[:avail]}"

        visual_w = cell_len(status_text)
        pad = NODE_W - 4 - visual_w
        status_line = f"{side} {status_text}{' ' * max(0, pad)} {side}"

        box_lines = [top, id_line, title_line, status_line, bot]

        output = Text()
        for dy, bl in enumerate(box_lines):
            line = Text()
            for char_idx, ch in enumerate(bl):
                is_border = (dy == 0 or dy == len(box_lines) - 1
                             or char_idx == 0 or char_idx == len(bl) - 1)
                if self._is_selected:
                    style = "bold cyan" if is_border else f"{node_style} {bg_style}".strip()
                elif is_border:
                    style = "dim"
                else:
                    style = f"{node_style} {bg_style}".strip()
                line.append(ch, style=style)
            # Apply special styles for auto-target marker
            if dy == 1 and self._is_auto_target:
                target_dx = 2 + len(display_id[:max_id_len - 2]) + 1
                if target_dx < len(bl):
                    line.stylize(f"bold magenta {bg_style}".strip(), target_dx, target_dx + 1)
            # Apply loop marker styles
            if dy == 3 and loop_marker and loop_style:
                marker_offset = 2 + len(f"{icon} {status}") + 1
                marker_len = len(loop_marker)
                line.stylize(f"{loop_style} {bg_style}".strip(), marker_offset, marker_offset + marker_len)

            output.append(line)
            if dy < len(box_lines) - 1:
                output.append("\n")

        return output
