"""Widget showing guide workflow progress with step indicators."""

from textual.widget import Widget
from textual.reactive import reactive
from rich.text import Text
from rich.console import RenderableType

from pm_core.guide import STEP_ORDER, STEP_DESCRIPTIONS


# Steps that are interactive (user-facing)
INTERACTIVE_STEPS = [s for s in STEP_ORDER if s not in ("all_in_progress", "all_done")]

# Unicode markers for step states
MARKER_COMPLETED = "\u2713"  # checkmark
MARKER_CURRENT = "\u25b6"    # right-pointing triangle
MARKER_FUTURE = "\u25cb"     # empty circle


class GuideProgress(Widget):
    """Displays guide workflow steps with progress indication."""

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

        # Header
        output.append("Guide Workflow\n", style="bold underline")
        output.append("\n")

        try:
            current_idx = STEP_ORDER.index(self.current_step)
        except ValueError:
            current_idx = 0

        for i, step in enumerate(INTERACTIVE_STEPS):
            step_idx = STEP_ORDER.index(step)
            step_num = i + 1
            description = STEP_DESCRIPTIONS.get(step, step)

            # Determine step state and styling
            if step_idx < current_idx:
                # Completed step
                marker = MARKER_COMPLETED
                marker_style = "bold green"
                text_style = "green"
            elif step_idx == current_idx:
                # Current step
                marker = MARKER_CURRENT
                marker_style = "bold cyan"
                text_style = "bold cyan"
            else:
                # Future step
                marker = MARKER_FUTURE
                marker_style = "dim"
                text_style = "dim"

            # Build line
            output.append("  ")
            output.append(marker, style=marker_style)
            output.append(f" {step_num}. {description}\n", style=text_style)

        output.append("\n")

        # Show hint based on step
        output.append("Guide running in adjacent pane\n", style="italic yellow")
        output.append("\n")
        output.append("Press ", style="dim")
        output.append("g", style="bold")
        output.append(" to relaunch guide    ", style="dim")
        output.append("x", style="bold")
        output.append(" to dismiss\n", style="dim")

        return output
