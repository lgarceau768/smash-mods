"""Form screens for every action the CLI supports (build/deploy/backup/
verify/unlock-save/dedupe). Curate has its own dedicated flow (see
curate_review.py) rather than a plain form here.

Every submit handler builds its argv via the matching commands.py *_argv()
function, then pushes LiveOutputScreen to actually run it -- forms never
touch runner.run or subprocess directly. For the four commit-guarded actions
(deploy, backup restore, dedupe, unlock-save), a commit=True submit first
shows modals.confirm.ConfirmModal; only a confirmed Yes proceeds to build and
run the --commit argv. This replaces commands._confirm_commit's terminal
prompt for the TUI path -- see commands.py's and live_output.py's docstrings
for why.
"""

from __future__ import annotations

from textual.app import ComposeResult
from textual.containers import Vertical
from textual.screen import Screen
from textual.widgets import Button, Footer, Header, Input, RadioButton, RadioSet, Static, Switch

from ... import commands
from ..modals.confirm import ConfirmModal
from .live_output import LiveOutputScreen


class _FormScreen(Screen):
    """Shared back binding for every form screen, plus the confirm-then-run
    helper every commit-guarded action uses."""

    BINDINGS = [("escape", "app.pop_screen", "Back")]

    def _run(self, argv: list, *, title: str) -> None:
        self.app.push_screen(LiveOutputScreen(argv, title=title))

    def _confirm_then_run(self, argv: list, *, title: str, commit: bool) -> None:
        if not commit:
            self._run(argv, title=title)
            return

        def on_confirm(confirmed: bool | None) -> None:
            if confirmed:
                self._run(argv, title=title)

        self.app.push_screen(
            ConfirmModal(f"{title} -- this WRITES data. Really commit?"), callback=on_confirm
        )


class DeployFormScreen(_FormScreen):
    def __init__(self, profile: str = "roster") -> None:
        super().__init__()
        self._initial_profile = profile

    def compose(self) -> ComposeResult:
        yield Header()
        with Vertical(id="content"):
            yield Static("Deploy a profile onto the SD card. Dry run unless Commit is on.")
            yield Input(value=self._initial_profile, placeholder="Profile name", id="profile")
            yield Static("Base stack only (no mods):")
            yield Switch(id="base-only")
            yield Static("Commit (actually write to the card):")
            yield Switch(id="commit")
            yield Button("Deploy", id="submit", variant="primary")
        yield Footer()

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id != "submit":
            return
        profile = self.query_one("#profile", Input).value.strip() or "roster"
        base_only = self.query_one("#base-only", Switch).value
        commit = self.query_one("#commit", Switch).value
        argv = commands.deploy_argv(profile=profile, base_only=base_only, commit=commit)
        self._confirm_then_run(argv, title=f"Deploy '{profile}'", commit=commit)


class BackupFormScreen(_FormScreen):
    def compose(self) -> ComposeResult:
        yield Header()
        with Vertical(id="content"):
            yield Static("Backup / restore the SD card.")
            yield RadioSet(
                RadioButton("create", value=True),
                RadioButton("list"),
                RadioButton("verify"),
                RadioButton("restore"),
                id="action",
            )
            yield Input(placeholder="Backup path (verify/restore only)", id="path")
            yield Static("Exact restore (delete card files absent from backup):")
            yield Switch(id="exact")
            yield Static("Commit (restore only -- actually write):")
            yield Switch(id="commit")
            yield Button("Run", id="submit", variant="primary")
        yield Footer()

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id != "submit":
            return
        action_set = self.query_one("#action", RadioSet)
        action = str(action_set.pressed_button.label) if action_set.pressed_button else "create"
        path = self.query_one("#path", Input).value.strip()
        exact = self.query_one("#exact", Switch).value
        commit = self.query_one("#commit", Switch).value

        if action == "list":
            self._run(commands.backup_argv(list_=True), title="Backup (list)")
        elif action == "verify":
            if not path:
                self.app.notify("Enter a backup path to verify.", severity="warning")
                return
            self._run(commands.backup_argv(verify=path), title="Backup (verify)")
        elif action == "restore":
            if not path:
                self.app.notify("Enter a backup path to restore from.", severity="warning")
                return
            argv = commands.backup_argv(restore=path, exact=exact, commit=commit)
            self._confirm_then_run(argv, title=f"Restore backup '{path}'", commit=commit)
        else:
            self._run(commands.backup_argv(mode="archive"), title="Backup (create)")


class VerifyFormScreen(_FormScreen):
    def compose(self) -> ComposeResult:
        yield Header()
        with Vertical(id="content"):
            yield Static("Lint a workspace or profile for mod-layout problems.")
            yield Input(placeholder="Workspace (optional)", id="workspace")
            yield Input(placeholder="Profile (optional)", id="profile")
            yield Static("Strict (treat warnings as errors):")
            yield Switch(id="strict")
            yield Button("Verify", id="submit", variant="primary")
        yield Footer()

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id != "submit":
            return
        workspace = self.query_one("#workspace", Input).value.strip() or None
        profile = self.query_one("#profile", Input).value.strip() or None
        strict = self.query_one("#strict", Switch).value
        argv = commands.verify_argv(workspace=workspace, profile=profile, strict=strict)
        self._run(argv, title="Verify")


class UnlockSaveFormScreen(_FormScreen):
    def compose(self) -> ComposeResult:
        yield Header()
        with Vertical(id="content"):
            yield Static("Unlock every fighter in a save file so added characters' slots are reachable.")
            yield Input(placeholder="Path to system_data.bin", id="save")
            yield Static("Commit (actually patch the save file):")
            yield Switch(id="commit")
            yield Button("Unlock", id="submit", variant="primary")
        yield Footer()

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id != "submit":
            return
        save = self.query_one("#save", Input).value.strip()
        if not save:
            self.app.notify("Enter a save-file path first.", severity="warning")
            return
        commit = self.query_one("#commit", Switch).value
        argv = commands.unlock_save_argv(save, commit=commit)
        self._confirm_then_run(argv, title=f"Unlock save '{save}'", commit=commit)


class DedupeFormScreen(_FormScreen):
    def compose(self) -> ComposeResult:
        yield Header()
        with Vertical(id="content"):
            yield Static("Strip files from a cosmetic layer that another layer already overrides.")
            yield Input(placeholder="Layer to trim, e.g. reskin", id="layer")
            yield Input(value="roster", placeholder="Layer that wins on conflict", id="against")
            yield Static("Commit (actually remove the duplicate files):")
            yield Switch(id="commit")
            yield Button("Dedupe", id="submit", variant="primary")
        yield Footer()

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id != "submit":
            return
        layer = self.query_one("#layer", Input).value.strip()
        if not layer:
            self.app.notify("Enter a layer to trim first.", severity="warning")
            return
        against = self.query_one("#against", Input).value.strip() or "roster"
        commit = self.query_one("#commit", Switch).value
        argv = commands.dedupe_argv(layer=layer, against=against, commit=commit)
        self._confirm_then_run(argv, title=f"Dedupe '{layer}' against '{against}'", commit=commit)


class BuildFormScreen(_FormScreen):
    def compose(self) -> ComposeResult:
        yield Header()
        with Vertical(id="content"):
            yield Static("Fetch, unpack, verify, and stage every profile.")
            yield Static("Skip fetch (rebuild from what's already downloaded):")
            yield Switch(id="skip-fetch")
            yield Button("Build", id="submit", variant="primary")
        yield Footer()

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id != "submit":
            return
        skip_fetch = self.query_one("#skip-fetch", Switch).value
        argv = commands.build_argv(skip_fetch=skip_fetch)
        self._run(argv, title="Build")


class CreateWorkspaceFormScreen(_FormScreen):
    def compose(self) -> ComposeResult:
        yield Header()
        with Vertical(id="content"):
            yield Static(
                "Add a new, empty workspace -- a category to move mods into, or target "
                "when curating or building a custom profile."
            )
            yield Input(placeholder="Workspace name, e.g. my-custom-layer", id="name")
            yield Button("Create workspace", id="submit", variant="primary")
        yield Footer()

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id != "submit":
            return
        name = self.query_one("#name", Input).value.strip()
        if not name:
            self.app.notify("Enter a workspace name first.", severity="warning")
            return
        argv = commands.create_workspace_argv(name)

        async def on_done(code: int | None) -> None:
            if code != 0:
                return
            self.app.pop_screen()
            home = self.app.screen
            await home._load_nav()
            home.select_workspace(name)

        self.app.push_screen(LiveOutputScreen(argv, title=f"Create workspace '{name}'"), callback=on_done)
