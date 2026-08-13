# run_menu.py wires DeepSeek + RuntimeController into the PyObjC menu shell.

from __future__ import annotations

from murphy.ui.menu_app import main as run_menu_main


def run_menu() -> int:
    """Launch the macOS menu bar app; blocks until Quit."""
    return run_menu_main()
