"""Widget showing guide workflow progress as a setup checklist."""

from textual.widget import Widget
from textual.reactive import reactive
from rich.text import Text
from rich.console import RenderableType

from pm_core.guide import STEP_ORDER


# Steps that are interactive (user-facing in the guide)
INTERACTIVE_STEPS = [s for s in STEP_ORDER if s not in ("ready_to_work", "all_in_progress", "all_done")]

# Unicode markers for checklist states
MARKER_DONE = "\u2713"     # checkmark
MARKER_CURRENT = "\u25b6"  # right-pointing triangle
MARKER_TODO = "\u25cb"     # empty circle

# Map guide steps to what the user actually needs to create.
# Each entry: (label, done_after_steps)
#   label: what to show in the checklist
#   done_after_steps: the step that, once reached, means this item exists
_CHECKLIST = [
    ("Project file", {"initialized", "has_plan_draft", "has_plan_prs"}),
    ("Plan file", {"has_plan_draft", "has_plan_prs"}),
    ("PRs loaded", {"has_plan_prs"}),
]


class GuideProgress(Widget):
    """Displays a setup checklist showing what's been created and what's next."""

    current_step: reactive[str] = reactive("no_project")

    def __init__(self, current_step: str = "no_project", **kwargs):
        super().__init__(**kwargs)
        self.current_step = current_step

    def update_step(self, step: str) -> None:
        """Update the current step and refresh display."""
        self.current_step = step
        self.refresh()

    def render(self) -> RenderableType:
        output = Text()

        output.append("Project Setup\n", style="bold underline")
        output.append("\n")

        try:
            current_idx = STEP_ORDER.index(self.current_step)
        except ValueError:
            current_idx = 0

        # Build the set of steps that are "done" (before current)
        done_steps = set(STEP_ORDER[:current_idx])

        found_current = False
        for label, done_after in _CHECKLIST:
            # Item is done if any of its done_after steps are in done_steps
            is_done = bool(done_after & done_steps)

            if is_done:
                marker = MARKER_DONE
                marker_style = "bold green"
                text_style = "green"
            elif not found_current:
                # First not-done item is the current one
                found_current = True
                marker = MARKER_CURRENT
                marker_style = "bold cyan"
                text_style = "bold cyan"
            else:
                marker = MARKER_TODO
                marker_style = "dim"
                text_style = "dim"

            output.append("  ")
            output.append(marker, style=marker_style)
            output.append(f" {label}\n", style=text_style)

        output.append("\n")
        output.append("Press ", style="dim")
        output.append("H", style="bold")
        output.append(" to start the setup guide\n", style="dim")

        return output
