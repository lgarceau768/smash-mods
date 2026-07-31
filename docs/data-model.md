# Data model: workspaces, profiles, and roster.toml

Everything in this repo is filesystem + TOML — there's no database. This doc
explains the four pieces and, more importantly, how a mod actually moves
through them, since "workspace" and "profile" read as near-synonyms until
you've seen the pipeline once.

## The one-sentence version

A **mod** lives in a **workspace** (a category folder); a **profile** is a
named combination of workspaces that gets deployed to the SD card; **which
workspace a mod is in is the only thing that determines which profiles it's
part of** — there's no separate per-mod pick-list at the profile level.

## The four pieces

### `roster.toml` — your personal pick-list

A gitignored, hand-curated (or Curate-generated) list of `[[mod]]` entries,
each pinned by GameBanana submission id + file + MD5 checksum:

```toml
[[mod]]
name = "Shadow-The-Hedgehog"
gamebanana_id = 578451
file = "578451-shadow_the_hedgehog_moveset.rar"
url = "https://gamebanana.com/dl/1447744"
md5 = "abbf939fabee2845cc642b980cd1fe60"
workspace = "roster"
```

The `workspace` field is the mod's **destination** — it says where `fetch.py`
+ `unpack.py` should unpack it, not where it currently is. Until it's been
fetched, this entry is the *only* place the mod exists; it doesn't have a
directory on disk yet. The schema is documented in
[`roster.toml.template`](../roster.toml.template).

### Workspaces — categories of mods on disk

A workspace is a directory under `workspaces/` (a symlink to a real data
folder, gitignored). There's no fixed list — `common.list_workspaces()`
just reads whatever directories exist. The built-in ones are `roster`
(added characters), `reskin`, `nsfw`, `celshaded`, `chao5`, `parked`, and
`hdr` (a selfcontained total conversion), but you can create more —
`smash-mods create-workspace NAME` (or the **Create workspace** action in
the TUI) — when the built-ins don't fit what you're building.

Each mod is one subdirectory: `workspaces/<workspace>/<Mod-Name>/`, laid out
exactly as ARCropolis expects on the card (top-level children drawn from
`common.GAME_PATHS` — `fighter`, `ui`, `sound`, etc).

**Mods can legitimately share a name across different workspaces.** E.g.
`reskin/Skin-Marth` and `nsfw/Skin-Marth` are two different files that happen
to share a name on purpose — see [Layering](#layering-same-named-mods-across-workspaces)
below. Any code that treats a mod's identity as just its name (not
`(workspace, name)`) will silently collapse two real, different mods into
one; this has been a real bug more than once in this codebase, so it's worth
remembering if you're extending it.

### Profiles — what actually gets deployed

Defined in `profiles.toml`. A profile is either:

- **Layered**: an ordered list of workspace names. `stage_layered()` copies
  each layer's mods in order; a later layer's mod **overwrites** an
  earlier layer's mod of the same name. This is how `nsfw` (`layers =
  ["roster", "reskin", "nsfw"]`) swaps in an adult skin for exactly the
  fighters that have one, while everyone else keeps their `reskin` look —
  the `nsfw` layer only needs to contain the fighters it actually swaps.
- **Selfcontained**: a single workspace that ships its own base stack (its
  own ARCropolis/Skyline fork, etc). `hdr` is the built-in example.

`smash-mods profiles` (or the Profiles screen in the TUI) shows every
profile's composition, resolved plugin count against the real 30/33-module
budget, and hardware-tested status.

### Layering: same-named mods across workspaces

Same-name-across-workspaces isn't a coincidence to guard against — it's how
overrides work. `nsfw`'s layer only needs to contain the fighters it
actually swaps an adult skin in for; everyone else falls through to
`reskin`'s version of that same mod name, then to `roster`'s, per the layer
order. This is exactly what `stage_layered()` does when it copies a
profile's layers onto the card, and it's why `verify.py`'s slot-collision
check has to model that same "later layer wins" precedence — otherwise two
copies of a mod that will never both reach the card (only one, the
last-layered one, does) get reported as a false conflict.

### Building a custom profile

`smash-mods create-profile` (CLI) or **ACTIONS → Create profile** (TUI) —
pick layered or selfcontained, pick workspace(s), see the resulting mod
count and plugin budget live, save. If the workspace you want doesn't exist
yet, create it first (see above).

## The pipeline, end to end

```
GameBanana ──survey──▶ Curate ──pin──▶ roster.toml ──fetch/unpack──▶ workspaces/<ws>/<mod>
                                                                              │
                                                                    (a mod's workspace is
                                                                     the only lever for
                                                                     profile membership)
                                                                              │
                                                                              ▼
                                                                        profiles.toml
                                                                     (layers = [ws, ws, ...]
                                                                      or selfcontained = ws)
                                                                              │
                                                                          deploy ──▶ SD card
```

Two distinct ways a mod ends up "in" a profile:

1. **A mod you don't have yet.** Curate it (survey → checklist → pin) or
   hand-edit `roster.toml`, with the right `workspace` field, then run
   **Build** to actually download and unpack it. Landing in the right
   workspace *is* joining every profile that layers that workspace — there's
   no separate step.
2. **A mod you already have.** Open its detail view (works for pending
   picks too, via the All Mods explorer) and use **Move to workspace** —
   physically relocates the directory (and updates its `roster.toml` entry)
   if it's already fetched, or just retargets the `roster.toml` entry if
   it's still pending. Either way, this is the one lever.

A mod's detail view always shows **"In profiles: ..."** (or, for a pending
pick, **"Once fetched, will be part of: ..."**) — derived live from its
current/target workspace against every profile in `profiles.toml`, so you
never have to compute this by hand.

## Quick reference

| Concept | Where it lives | What determines membership |
|---|---|---|
| Mod pick (not fetched) | `roster.toml` `[[mod]]` entry | its `workspace` field |
| Mod (fetched) | `workspaces/<ws>/<name>/` directory | which `<ws>` it's physically in |
| Workspace | a directory under `workspaces/` | just exists or doesn't (`create-workspace` to add one) |
| Profile | `profiles.toml` `[name]` table | its `layers` list, or `selfcontained` |
