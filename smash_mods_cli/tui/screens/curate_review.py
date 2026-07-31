"""CurateReviewScreen: survey GameBanana, then browse and choose which picks
actually get pinned into roster.toml -- instead of the old all-or-nothing
Report/Write toggle.

Three steps in one screen:
  1. Config -- pick a kind (movesets/skins/nsfw) and an optional limit.
  2. Survey -- runs the matching curate*.py script with --json, streaming its
     stderr progress live while capturing stdout (the final JSON candidate
     list) to parse once it finishes.
  3. Review -- every surveyed candidate appears as a checklist row, ALL
     selected by default (this is still "bulk curate": the default is to
     take everything survey found viable) -- uncheck any you don't want,
     then pin just the selected ones with --write-ids, via LiveOutputScreen.

Pinning to roster.toml is not the end of the story: the picks still need
Build to actually fetch/unpack them into a workspace before they show up
anywhere else in the app -- the confirmation after writing says so.
"""

from __future__ import annotations

import asyncio
import json

from textual import work
from textual.app import ComposeResult
from textual.containers import Vertical
from textual.screen import Screen
from textual.widgets import Button, Footer, Header, Input, RadioButton, RadioSet, RichLog, SelectionList, Static

from ... import commands
from ..modals.confirm import ConfirmModal
from .live_output import LiveOutputScreen

_ARGV_BUILDERS = {
    "movesets": commands.curate_movesets_argv,
    "skins": commands.curate_skins_argv,
    "nsfw": commands.curate_nsfw_argv,
}


class CurateReviewScreen(Screen):
    BINDINGS = [("escape", "app.pop_screen", "Back")]

    def __init__(self) -> None:
        super().__init__()
        self._candidates: list[dict] = []

    def compose(self) -> ComposeResult:
        yield Header()
        with Vertical(id="content"):
            with Vertical(id="curate-config-group"):
                yield Static(
                    "Survey GameBanana, then choose which picks actually get pinned into "
                    "roster.toml. Nothing is written until you review and confirm."
                )
                yield RadioSet(
                    RadioButton("movesets", value=True),
                    RadioButton("skins"),
                    RadioButton("nsfw"),
                    id="kind",
                )
                yield Input(placeholder="Limit (blank = default; ignored for nsfw)", id="limit")
                yield Button("Survey", id="survey-btn", variant="primary")

            with Vertical(id="curate-survey-group"):
                yield Static("[dim]Surveying...[/dim]", id="survey-title")
                yield RichLog(id="survey-log", wrap=True, highlight=False, markup=False, max_lines=2000)
                yield Static("", id="survey-status")

            with Vertical(id="curate-review-group"):
                yield Static(id="review-summary")
                yield SelectionList(id="candidates-select")
                yield Button("Pin selected to roster.toml", id="write-btn", variant="primary")
        yield Footer()

    def on_mount(self) -> None:
        self.query_one("#curate-survey-group").display = False
        self.query_one("#curate-review-group").display = False

    def _kind(self) -> str:
        kind_set = self.query_one("#kind", RadioSet)
        return str(kind_set.pressed_button.label) if kind_set.pressed_button else "movesets"

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "survey-btn":
            self._start_survey()
        elif event.button.id == "write-btn":
            self._do_write()

    def _start_survey(self) -> None:
        kind = self._kind()
        limit_text = self.query_one("#limit", Input).value.strip()
        argv_fn = _ARGV_BUILDERS[kind]
        if kind == "movesets":
            argv = argv_fn(json=True, limit=int(limit_text) if limit_text else 24)
        elif kind == "skins":
            argv = argv_fn(json=True, limit=int(limit_text) if limit_text else 0)
        else:
            argv = argv_fn(json=True)

        self.query_one("#curate-config-group").display = False
        self.query_one("#curate-survey-group").display = True
        self._run_survey(argv, kind)

    @work(exclusive=True)
    async def _run_survey(self, argv: list, kind: str) -> None:
        from ...paths import REPO_ROOT

        log = self.query_one("#survey-log", RichLog)
        status = self.query_one("#survey-status", Static)

        try:
            proc = await asyncio.create_subprocess_exec(
                *[str(a) for a in argv],
                cwd=str(REPO_ROOT),
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
        except OSError as exc:
            status.update(f"[red]Failed to start: {exc}[/red]")
            return

        stdout_chunks: list[bytes] = []

        async def read_stdout() -> None:
            assert proc.stdout is not None
            while True:
                chunk = await proc.stdout.read(4096)
                if not chunk:
                    break
                stdout_chunks.append(chunk)

        async def read_stderr() -> None:
            assert proc.stderr is not None
            buf = ""
            while True:
                chunk = await proc.stderr.read(4096)
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

        await asyncio.gather(read_stdout(), read_stderr())
        code = await proc.wait()

        if code != 0:
            status.update(f"[red]Survey exited with code {code} -- see log above.[/red]")
            return

        try:
            candidates = json.loads(b"".join(stdout_chunks).decode(errors="replace"))
        except json.JSONDecodeError:
            status.update("[red]Could not parse survey results.[/red]")
            return

        status.update("")
        self._show_review(candidates, kind)

    def _show_review(self, candidates: list[dict], kind: str) -> None:
        self._candidates = candidates
        self.query_one("#curate-survey-group").display = False
        self.query_one("#curate-review-group").display = True

        sel = self.query_one("#candidates-select", SelectionList)
        sel.clear_options()
        for c in candidates:
            sel.add_option((self._candidate_label(c, kind), c["id"], True))

        summary = self.query_one("#review-summary", Static)
        if candidates:
            summary.update(
                f"{len(candidates)} candidates found, all selected by default -- "
                "uncheck any you don't want, then pin the rest to roster.toml."
            )
        else:
            summary.update("No viable candidates found.")

    @staticmethod
    def _candidate_label(c: dict, kind: str) -> str:
        if kind == "movesets":
            return f"{c['name']}  ({c['likes']} likes, updated {c['updated']})"
        if kind == "skins":
            return f"{c['character']}: {c['name']}  ({c['likes']} likes, updated {c['updated']})"
        return f"{c['character']}: {c['name']}  ({c['likes']} likes) [{c.get('ratings', '')}]"

    def _do_write(self) -> None:
        sel = self.query_one("#candidates-select", SelectionList)
        ids = list(sel.selected)
        if not ids:
            self.app.notify("Nothing selected -- check at least one candidate first.", severity="warning")
            return
        kind = self._kind()
        argv = _ARGV_BUILDERS[kind](write_ids=ids)
        self.app.push_screen(
            LiveOutputScreen(argv, title=f"Pin {len(ids)} {kind} pick(s) to roster.toml"),
            callback=self._on_write_done,
        )

    def _on_write_done(self, code: int | None) -> None:
        if code != 0:
            return
        self.app.pop_screen()

        def on_confirm(run_build: bool | None) -> None:
            if run_build:
                from .action_forms import BuildFormScreen

                self.app.push_screen(BuildFormScreen())

        self.app.push_screen(
            ConfirmModal(
                "Pinned to roster.toml. These mods aren't fetched yet -- run Build now to "
                "download and unpack them into their workspace?",
                yes_label="Run Build now",
                no_label="Not now",
                danger=False,
            ),
            callback=on_confirm,
        )
