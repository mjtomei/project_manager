"""TUI package for the project manager."""

from textual.message import Message


def item_message(
    name: str, field: str
) -> tuple[type[Message], type[Message]]:
    """Create a Selected/Activated message class pair with a single ID field.

    Args:
        name: Class name prefix (e.g. "PR", "Plan", "Test").
        field: Attribute name on the message instance (e.g. "pr_id").

    Returns:
        (Selected, Activated) tuple of Message subclasses.
    """

    def _make(suffix: str, doc: str) -> type[Message]:
        cls_name = f"{name}{suffix}"

        def __init__(self, value: str) -> None:
            setattr(self, field, value)
            Message.__init__(self)

        return type(cls_name, (Message,), {"__init__": __init__, "__doc__": doc})

    selected = _make("Selected", f"Fired when a {name.lower()} is selected.")
    activated = _make(
        "Activated", f"Fired when Enter is pressed on a {name.lower()}."
    )
    return selected, activated
