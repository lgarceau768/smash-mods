"""Shared Rich console instance, so every module prints through the same one."""

from __future__ import annotations

from rich.console import Console

console = Console()
