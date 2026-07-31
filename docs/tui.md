# The interactive TUI

`smash-mods` with no arguments launches a full-screen Textual app. This is a
second front end alongside the Typer subcommands (`smash-mods build`,
`smash-mods deploy`, ...) — both call into the same `smash_mods_cli/commands.py`
functions, so neither can drift from the other. If you'd rather script things,
every command in the [README's table](../README.md#commands) works exactly
the same from a plain shell.

If you're unclear on "workspace" vs "profile" vs `roster.toml`, read
[`data-model.md`](data-model.md) first — this doc assumes that mental model.

## Launching

- `smash-mods` — normal launch. Shows the welcome tour automatically the
  very first time (tracked in `~/.config/smash-mods/first_run_seen`).
- `smash-mods --first-time` — show the welcome tour again regardless.
- Piped or non-interactive stdio (`smash-mods | cat`, `smash-mods < /dev/null`,
  CI) — prints a short message and exits 0 instead of hanging or trying to
  draw a TUI it can't.
- `?` any time inside the app reopens the welcome tour.

## Layout

Left nav, right content pane:

- **MODS** → **All mods** — opens the [explorer](#all-mods-explorer)
  (see below). Not embedded in the nav pane itself; it's a full dedicated
  screen because it needs room for filters, a results table, and a preview
  pane.
- **WORKSPACES** — one row per workspace directory. Selecting one loads its
  mods (fetched only — a plain workspace listing is exactly what's on disk)
  into the mod list on the right, with a status line showing which
  profile(s) use it.
- **PROFILES** — one row per `profiles.toml` entry. Selecting one loads the
  *resolved* mod set that profile would actually deploy (layers merged,
  later wins). `p` jumps here from anywhere.
- **ACTIONS** — every action (see [below](#actions)), each showing a
  plain-English description of what it does — and whether it can write real
  data — before you commit to opening it.

Arrow keys or mouse clicks both work throughout; `/` focuses the search box
in whatever list-view screen is active; `Esc` goes back; `q` quits.

## All Mods explorer

The primary way to browse the whole mod collection — every mod you have
data on, fetched or not, in one place:

- **Search** — matches name, workspace, and category.
- **Workspace filter** / **Status filter** (all / fetched / pending) /
  **Sort** (name A-Z/Z-A, workspace) — all live-updating `Select` dropdowns.
- **Results table** — Name / Workspace / Status / Category columns.
- **Preview pane** — arrowing to a row updates a text summary immediately,
  and (debounced ~300ms, so fast scrolling doesn't fire a fetch per row it
  passes through) a thumbnail: the mod's local `preview.webp` if it's
  fetched and has one, otherwise a cached-or-lazily-fetched GameBanana
  screenshot if it's a pinned pick. No image is shown if neither exists —
  that's not a bug, some mods just don't have one.
- **Open full detail** (button, or select the row) — opens the same
  [mod detail modal](#mod-detail) workspace browsing uses.

Deliberately does **not** load a thumbnail for every visible row — with a
few hundred mods that would mean a network fetch per row and would make
scrolling miserable. Only the currently-highlighted row's image is ever
resolved.

## Mod detail

Opens for any mod, fetched or pending:

- **Fetched**: `info.toml` fields if present (display name, category,
  authors, version, description), which of the recognised game-data
  directories (`fighter`, `ui`, `sound`, ...) it actually has, and its local
  `preview.webp` rendered inline if one exists.
- **Pending** (not fetched yet): target workspace, and which profiles it
  *would* join once fetched. No local file info, obviously — there's
  nothing on disk yet.
- **GameBanana enrichment** (either case, if the mod correlates to a
  `roster.toml` pick with a `gamebanana_id`): a background fetch fills in
  the full submission description, author, like/view counts, and up to 6
  screenshots as a **carousel** (`←`/`→` or the Prev/Next buttons) — cached
  under `build/.gamebanana_cache/` after the first fetch, so reopening the
  same mod is instant.
- **In profiles**: always shown, derived live from the mod's current (or
  target) workspace against `profiles.toml` — never stale, never computed
  by hand.
- **Move to workspace**: pick a target from the dropdown, press Move.
  Physically relocates the directory (and updates its `roster.toml` entry)
  if the mod is already fetched; just updates the `roster.toml` entry if
  it's still pending. This is *the* lever for changing which profiles a mod
  is part of.

Images always keep their source aspect ratio — the `Image` widget and its
container both use `width: auto; height: auto` in CSS specifically so
Textual asks for the image's own preferred (aspect-correct) size instead of
stretching it to fill an arbitrary box.

## Actions

Every action lives under ACTIONS in the nav and shows its own description
before you open it:

| Action | Does |
|---|---|
| Create workspace | Add a new, empty workspace — needed before a truly custom profile |
| Create profile | Pick layered/selfcontained workspaces, see live mod count + plugin budget, save |
| Build | Fetch + unpack + verify + stage everything pinned in `roster.toml` |
| Deploy | Copy a staged profile onto the card. Dry run unless Commit is on |
| Backup | Snapshot/restore the card's mods folder. Only restore writes |
| Verify | Lint a workspace/profile for layout problems. Always read-only |
| Curate | Survey GameBanana → review as a checklist (all selected by default) → pin selected picks |
| Toggle mods | Instant enable/disable on the card by renaming a mod's folder |
| Dedupe | Strip a cosmetic layer's files that a higher-priority layer already overrides |
| Unlock save | Patch a save file so every fighter slot is reachable |

### Live output, not a bare terminal

Every action runs its underlying script asynchronously with piped stdio,
streamed into a scrolling log inside the app (`LiveOutputScreen`) — it never
suspends the TUI and hands the terminal to a subprocess. Progress bars that
redraw a single line via `\r` (rsync, curl) show up as a single live status
line above the log instead of a wall of carriage-return garbage; real
`\n`-terminated lines scroll normally. You can't close the output screen
while its process is still running (`Esc`/Close just warns) — wait for it to
finish, then close.

### The safety model

Four actions map onto a script's own `--commit` flag: **Deploy**, **Backup
restore**, **Dedupe**, **Unlock save**. Turning Commit on and submitting
always shows a native confirm dialog ("this WRITES data — really commit?")
*before* anything runs — cancel and nothing happens. Every one of these
scripts is dry-run-by-default independent of the TUI too, so this is a
second layer, not the only one.

Non-destructive actions (enable/disable a mod, create a workspace, pin
curate picks, create/build a profile) don't need this — they're either
instantly reversible or, for `roster.toml`/`profiles.toml`, one `git diff`
away from undone (both are regenerable/git-tracked; only the SD card and a
save file are genuinely hard to undo).

## Keybindings

| Key | Where | Does |
|---|---|---|
| `/` | most list screens | Focus the search box |
| `↑`/`↓`, click | everywhere | Move / select |
| `Enter` | list rows | Open (mod detail, action, profile drill-down) |
| `Esc` | everywhere | Back / close (blocked while an action is still running) |
| `p` | Home | Jump to Profiles |
| `e` / `d` | Home, mod list focused | Enable / disable the selected mod on the card |
| `←`/`→` | mod detail | Previous / next GameBanana screenshot |
| `?` | everywhere | Reopen the welcome tour |
| `q` | Home | Quit |
