"""ConfirmModal: a native Yes/No dialog, replacing commands._confirm_commit's
terminal-based Confirm.ask() prompt for the TUI.

The four commit-guarded actions (deploy, backup restore, dedupe, unlock-save)
must still get an explicit "really do this?" confirmation before writing real
data -- that safety property doesn't change. What changes is *how* it's
asked: a modal inside the TUI instead of suspending to a raw terminal prompt,
now that guarded actions run through LiveOutputScreen (streamed output)
rather than App.suspend(). See LiveOutputScreen's module docstring for why.
"""

from __future__ import annotations

from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical
from textual.screen import ModalScreen
from textual.widgets import Button, Static


class ConfirmModal(ModalScreen[bool]):
    """Dismisses with True (confirmed) or False (cancelled/escaped).

    Defaults are worded/styled for the "this WRITES data, are you sure"
    case; pass yes_label/no_label/danger=False to reuse it for a friendlier
    yes/no nudge (e.g. "run Build now?") instead.
    """

    BINDINGS = [("escape", "cancel", "Cancel")]

    def __init__(
        self,
        message: str,
        *,
        yes_label: str = "Yes, really do it",
        no_label: str = "Cancel",
        danger: bool = True,
    ) -> None:
        super().__init__()
        self._message = message
        self._yes_label = yes_label
        self._no_label = no_label
        self._danger = danger

    def compose(self) -> ComposeResult:
        style = "bold yellow" if self._danger else "bold"
        with Vertical(id="confirm-panel"):
            yield Static(f"[{style}]{self._message}[/{style}]", id="confirm-message")
            with Horizontal(id="confirm-buttons"):
                yield Button(self._no_label, id="confirm-no")
                yield Button(self._yes_label, id="confirm-yes", variant="error" if self._danger else "primary")

    def on_button_pressed(self, event: Button.Pressed) -> None:
        self.dismiss(event.button.id == "confirm-yes")

    def action_cancel(self) -> None:
        self.dismiss(False)
