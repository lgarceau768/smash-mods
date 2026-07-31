# Architecture notes

For anyone changing this code (including a future Claude session). Covers
how the pieces fit together and the non-obvious decisions/gotchas that took
real debugging to find — the goal is to not have to rediscover them.

## Package layout

```
scripts/                    real logic, stdlib-only Python 3.11+ / POSIX shell,
                             zero third-party deps, every script directly runnable
                             on its own (python3 scripts/verify.py, ./scripts/build.sh)

smash_mods_cli/
├── main.py                  Typer app -- one subcommand per action
├── commands.py               *_argv()/*_cmd() pairs -- the single dispatch layer
├── runner.py                  subprocess.run() with inherited stdio, for *_cmd()
├── profiles_view.py            `smash-mods profiles` table (read-only, no subprocess)
├── paths.py                     REPO_ROOT/SCRIPTS constants; importing it puts
│                                 scripts/ on sys.path so `import common` works
├── ui.py                        shared rich.Console instance
└── tui/                     the full-screen Textual app (second front end)
    ├── app.py                   SmashModsApp
    ├── first_run.py              welcome-tour-seen marker (~/.config/smash-mods/)
    ├── actions_catalog.py         ActionInfo table -- single source of truth for
    │                              every action's label/description in the nav
    ├── screens/                  one file per screen (home, all_mods, mod_detail,
    │                              profiles, action_forms, curate_review, toggle,
    │                              profile_wizard, live_output, welcome)
    ├── modals/confirm.py          ConfirmModal -- native Yes/No dialog
    └── widgets/mod_list.py        ModEntry/ModListView -- filterable list widget
                                    (used by workspace/profile browsing, not by
                                    the All Mods explorer, which uses DataTable)
```

**Invariant**: `scripts/` never imports from `smash_mods_cli/`, and stays
zero-dependency so every script keeps working standalone. `smash_mods_cli/`
is purely a front end over it.

## The dispatch pattern

Every action has a `*_argv()` function (builds the argv list, pure) and a
`*_cmd()` function (`*_argv()` + guardrail + `runner.run()`, for the Typer
CLI). Both Typer *and* the TUI ultimately run the exact same argv — Typer via
`*_cmd()` (blocking `subprocess.run()`, inherited stdio — correct for a real
terminal), the TUI via `*_argv()` directly, executed by `LiveOutputScreen`
(async `create_subprocess_exec()`, piped stdio, streamed into the app).

The TUI **never** calls `*_cmd()` — it can't use the synchronous,
inherited-stdio subprocess call without blocking Textual's event loop and
defeating the whole point of streaming output live (see below). This means
the TUI is responsible for its own guardrail before building a `--commit`
argv (see "Safety model" below) — `commands._confirm_commit()` is only
reached via `*_cmd()`, i.e. only from the Typer CLI path.

## Why `LiveOutputScreen` instead of `App.suspend()`

The TUI used to run every action via `App.suspend()`: hand the real terminal
to the subprocess (correct for rsync/curl progress bars, which need raw
inherited stdio), then resume. This worked but meant the *entire screen*
blinked out to a bare terminal and back for every single action — jarring,
reads as broken rather than "the app is doing something."

`tui/screens/live_output.py` replaces this: `asyncio.create_subprocess_exec()`
with piped (not inherited) stdout+stderr, read incrementally and written into
a `RichLog`. The one real cost: a script's own `\r`-redrawn progress line
can't be captured as a single redrawing line the normal terminal way —
instead, `\r`-terminated segments update a single status `Static` above the
log (so you still see "45%... 82%... done" in one place), while real
`\n`-terminated lines scroll normally below it. Less faithful to raw
terminal output, but the picture never leaves the app.

## Why `textual_image` has to be imported before `SmashModsApp()` starts

`textual-image`'s terminal-graphics-protocol detection
(`textual_image/renderable/tgp.py`'s `query_terminal_support()`) sends an
escape sequence and reads the raw response from stdin — synchronously, once,
at **first import** of `textual_image.renderable` (or anything that imports
it, like `textual_image.widget`). Its own docstring says outright: *"this
function will not work anymore once Textual is started. Textual runs a
thread to read stdin and will grab the response."*

We used to import `textual_image.widget` lazily, inside `mod_detail.py`,
first triggered when a modal actually needed to show an image — by which
point Textual's own driver had already been reading stdin for a while, so
detection always failed and every image silently rendered via the unicode
fallback, in *any* terminal, Kitty included. Fixed by importing it once,
explicitly, in `tui/__init__.py`'s `run_tui()`, before `SmashModsApp().run()`.
Detection happens once, against a "quiet" terminal, and every later (lazy)
import elsewhere just reuses Python's cached module — no need to import it
early anywhere else.

## Image aspect ratio: `width: auto; height: auto` is load-bearing

Setting an explicit fixed height on an image's *container* (the original
approach, to solve a "collapses to 0 rows" problem) is **not** enough to get
a correctly-proportioned image — Textual only asks a widget for its own
preferred content size (`get_content_width`/`get_content_height`, where
`textual_image`'s aspect-ratio-preserving fit logic lives) when that
widget's *own* CSS marks the relevant dimension `auto`. Leave it unset and
Textual just stretches the widget to fill whatever box its container
resolves to, ignoring the source image's proportions entirely — which reads
as photos being randomly squashed or cropped.

The fix (`styles.tcss`): `width: auto; height: auto` on the `Image` widgets
themselves (not just their containers), and the *containers* also get
`height: auto` (not a hardcoded row count) so they naturally size to fit
whatever the now-correctly-computed child image size turns out to be. No
circular-collapse problem in practice: `ImageSize.get_cell_size()` falls back
to an effectively-unbounded max when the container's height hasn't resolved
yet, so the image's own aspect-ratio math (driven by the resolved width) is
what actually determines the final height, and the container then sizes to
match it.

## GameBanana enrichment and caching

`scripts/gamebanana.py` — stdlib `urllib`, no dependency added to `scripts/`.
Three things worth knowing:

- **Screenshot resolution**: GameBanana only generates a full set of resized
  variants (`_sFile220`, `_sFile530`, `_sFile800`, ...) for a submission's
  *first* screenshot. Secondary screenshots in the gallery often only expose
  a 100×56 `_sFile100` thumbnail via this API response. The bare `_sFile`
  field (no size prefix) is always present and is the **original, unresized
  upload** — `screenshot_urls()` falls back to that, not `_sFile100`, or
  every screenshot past the first one would silently render at thumbnail
  resolution.
- **Caching**: `fetch_profile()` (JSON, 7-day TTL) and `fetch_image_bytes()`
  (images, no TTL — a screenshot doesn't change) both cache under
  `build/.gamebanana_cache/` (gitignored, disposable). `has_fresh_cache()`
  lets a caller check before deciding whether to show a "fetching..."
  message, so a cache hit is *visibly* (not just theoretically) different
  from a live fetch.
- **Correlating a mod to a GameBanana id**: `common.roster_entry(name)`
  tries an exact match against `roster.toml`'s `name` field first, then
  falls back to a prefix match — workspace directories sometimes get an
  extra tag appended by hand after unpacking (e.g.
  `Shadow-The-Hedgehog` → `Shadow-The-Hedgehog-{Moveset}-Shadow`), so an
  exact-only match misses a lot of real mods in practice.

## `(workspace, name)`, not `name`, is a mod's real identity

Mods can legitimately share a name across different workspaces by design
(`reskin/Skin-Marth` vs `nsfw/Skin-Marth` — see
[`data-model.md`](data-model.md#layering-same-named-mods-across-workspaces)).
Anything that dedupes or keys
mods by name alone will silently collapse two distinct, real files into one.
This has bitten the codebase twice already:

- `common.all_known_mods()` — originally keyed its unification dict by
  `path.name` alone; fixed to key by `(workspace, name)`.
- `AllModsScreen`'s `DataTable` — originally used the bare name as the row
  `key`, which crashed outright (`DuplicateKey`) the moment two same-named
  mods from different workspaces were both visible; fixed with a
  `f"{workspace}::{name}"` composite key (`_row_key()`).

If you add another place that needs to identify "a specific mod," key it by
the pair, not the name.

## Async gotcha: `HomeScreen._load_nav()` must be awaited before selecting

`ListView.clear()` and `.extend()` are async DOM operations (`AwaitRemove`/
`AwaitMount`) — calling them without awaiting, then immediately trying to
find-and-select a specific new item (e.g. right after creating a workspace
or a profile), can run against a `nav.children` that's transiently *doubled*
(old items not yet removed, new ones already added) or simply stale. Every
caller that needs to select something right after a nav rebuild — see
`select_profile()`/`select_workspace()`'s call sites in `action_forms.py`
and `profile_wizard.py` — must be an `async def` callback and
`await home._load_nav()` before calling `select_*()`. `push_screen(...,
callback=...)` accepts an async callable for exactly this reason.

## Testing approach

No real UI-testing framework beyond Textual's own headless harness
(`App.run_test()`), used throughout development rather than committed as a
test suite (this repo's only committed tests are `tests/test_verify.py`,
for the linter). Useful patterns if you're verifying a change:

- `App.run_test()` runs headless — no real terminal needed, works in any
  sandboxed/CI environment.
- `App.suspend()` (and thus anything that calls it) raises
  `SuspendNotSupported` under the headless test driver — not relevant
  anymore since the TUI no longer uses it, but worth knowing if you're
  testing `LiveOutputScreen`'s async subprocess path instead (which works
  fine headless, since it doesn't need a real terminal at all).
- Widgets that mutate via `.clear()`/`.extend()`/`.mount()` need an
  `await pilot.pause()` afterward before asserting on `.children` — see the
  async gotcha above.
- `LiveOutputScreen` and `ConfirmModal` never auto-dismiss — a test (or a
  real user) must press Close/Yes/No explicitly, or `push_screen(...,
  callback=...)` never fires.
- Never run the four commit-guarded actions for real against actual
  hardware/save-file data while testing — stub `commands.*_argv` or the
  screen's `run_suspended`/`LiveOutputScreen` reference instead, and verify
  argv construction and guardrail wiring without executing anything.
