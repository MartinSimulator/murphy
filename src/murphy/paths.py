"""Filesystem locations for Murphy runtime state."""

from __future__ import annotations

from pathlib import Path

# Checked-in defaults live under config/ in the repository.
# Mutable user state (SQLite journal, local settings) belongs here.
USER_DATA_DIR = Path.home() / "Library" / "Application Support" / "Murphy"
