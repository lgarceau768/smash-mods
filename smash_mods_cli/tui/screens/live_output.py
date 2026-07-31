"""LiveOutputScreen: run a script's argv and stream its output live, inside
the TUI, instead of suspending to the raw terminal.

App.suspend() (the original approach -- see git history) handed the real
terminal to the subprocess so rsync/curl progress bars would render, but it
meant the whole screen blinked out to a bare terminal and back for every
action, which reads as broken rather than "the app is doing something."
This runs the subprocess asynchronously with piped (not inherited) stdio and
streams it into a RichLog here instead.

The one real cost: progress bars that redraw a single line via carriage
returns (\\r) can't be captured as one redrawing line the way a real
terminal would -- instead, \\r-terminated segments update a single status
line here (so you still see "45%... 82%... done" livein one place) while
real \\n-terminated lines go to the scrolling log below. Less faithful to
the original terminal output, but the picture never leaves the app.

Because this bypasses commands.py's own subprocess execution (which inherits
stdio and blocks synchronously -- fine for the Typer CLI, wrong for a piped
async read), the four commit-guarded actions no longer get their "really
commit?" prompt from commands._confirm_commit -- callers must show
modals.confirm.ConfirmModal themselves before ever building an argv with
--commit. See action_forms.py for that pattern.
"""

from __future__ import annotations

import asyncio

from textual.app import ComposeResult
from textual.containers import Vertical
from textual.screen import ModalScreen
from textual.widgets import Button, RichLog, Static


class LiveOutputScreen(ModalScreen[int]):
    BINDINGS = [("escape", "maybe_dismiss", "Close")]

    def __init__(self, argv: list, *, title: str = "Running...") -> None:
        super().__init__()
        self._argv = [str(a) for a in argv]
        self._title = title
        self._exit_code: int | None = None

    def compose(self) -> ComposeResult:
        with Vertical(id="live-panel"):
            yield Static(f"[bold]{self._title}...[/bold]", id="live-title")
            yield RichLog(id="live-log", wrap=True, highlight=False, markup=False, max_lines=4000)
            yield Static("", id="live-status")
            yield Button("Close", id="live-close-btn", disabled=True)

    def on_mount(self) -> None:
        self.run_worker(self._run_process(), exclusive=True)

    async def _run_process(self) -> None:
        from ...paths import REPO_ROOT

        log = self.query_one("#live-log", RichLog)
        status = self.query_one("#live-status", Static)

        try:
            proc = await asyncio.create_subprocess_exec(
                *self._argv,
                cwd=str(REPO_ROOT),
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.STDOUT,
            )
        except OSError as exc:
            log.write(f"[failed to start: {exc}]")
            self._finish(1)
            return

        assert proc.stdout is not None
        buf = ""
        while True:
            chunk = await proc.stdout.read(4096)
            if not chunk:
                break
            buf += chunk.decode(errors="replace")
            while True:
                idx_r = buf.find("\r")
                idx_n = buf.find("\n")
                candidates = [i for i in (idx_r, idx_n) if i != -1]
                if not candidates:
                    break
                idx = min(candidates)
                line, buf = buf[:idx], buf[idx + 1 :]
                if idx == idx_n:
                    if line:
                        log.write(line)
                else:
                    status.update(line)
        if buf.strip():
            log.write(buf)

        code = await proc.wait()
        self._finish(code)

    def _finish(self, code: int) -> None:
        self._exit_code = code
        title = self.query_one("#live-title", Static)
        if code == 0:
            title.update(f"[bold green]{self._title} -- done[/bold green]")
        else:
            title.update(f"[bold red]{self._title} -- exited with code {code}[/bold red]")
        self.query_one("#live-status", Static).update("")
        self.query_one("#live-close-btn", Button).disabled = False

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "live-close-btn" and self._exit_code is not None:
            self.dismiss(self._exit_code)

    def action_maybe_dismiss(self) -> None:
        if self._exit_code is not None:
            self.dismiss(self._exit_code)
        else:
            self.app.notify("Still running -- wait for it to finish.", severity="warning")
