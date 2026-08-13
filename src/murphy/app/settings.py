"""Load/Save project_root under the Application Support directory"""

from __future__ import annotations

from pathlib import Path
from murphy.paths import USER_DATA_DIR

_SETTINGS_FILE = USER_DATA_DIR / "project_root.txt"


# Load the project_root from the Application Support directory
def load_project_root() -> Path | None:
    if not _SETTINGS_FILE.exists():
        return None
    text = _SETTINGS_FILE.read_text(encoding="utf-8").strip()
    if not text:
        return None
    return Path(text)

# Save the project_root to the Application Support directory
def save_project_root(project_root: Path) -> None:
    root = project_root.expanduser().resolve()
    USER_DATA_DIR.mkdir(parents=True, exist_ok=True)
    _SETTINGS_FILE.write_text(str(root), encoding="utf-8")