"""Filterable list of mods, backed by an in-memory cache (not a disk re-scan
per keystroke).
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from textual.widgets import Label, ListItem, ListView


@dataclass
class ModEntry:
    """One browsable mod row. `path` is None for a roster.toml pick that has
    no directory in workspaces/ yet (not fetched/unpacked)."""

    name: str
    path: Path | None
    subtitle: str = ""

    def matches(self, query: str) -> bool:
        query = query.lower()
        return query in self.name.lower() or query in self.subtitle.lower()


class ModListView(ListView):
    """A ListView of ModEntry rows with live substring filtering."""

    def __init__(self, **kwargs) -> None:
        super().__init__(**kwargs)
        self._all_entries: list[ModEntry] = []

    def load(self, entries: list[ModEntry]) -> None:
        self._all_entries = entries
        self._populate(entries)

    def filter_text(self, query: str) -> None:
        if not query:
            self._populate(self._all_entries)
            return
        self._populate([e for e in self._all_entries if e.matches(query)])

    def _populate(self, entries: list[ModEntry]) -> None:
        self.clear()
        items = []
        for entry in entries:
            label = entry.name if not entry.subtitle else f"{entry.name}  [dim]{entry.subtitle}[/dim]"
            item = ListItem(Label(label))
            item.mod_entry = entry  # type: ignore[attr-defined]
            items.append(item)
        self.extend(items)
        # ListView.clear() resets index to None and extend() doesn't restore it,
        # so without this the first row is never highlighted/selectable.
        self.index = 0 if items else None

    @property
    def selected_entry(self) -> ModEntry | None:
        highlighted = self.highlighted_child
        if highlighted is None:
            return None
        return getattr(highlighted, "mod_entry", None)
