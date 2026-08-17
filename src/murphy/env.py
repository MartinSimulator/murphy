# env.py loads optional repo-local .env into os.environ.

from __future__ import annotations

import os
from pathlib import Path


def load_dotenv(path: Path | None = None) -> Path | None:
    """
    Load KEY=VALUE pairs from a .env file if present.

    Non-empty existing environment variables win. Empty or whitespace-only
    values are treated as unset so a blank `export DEEPSEEK_API_KEY=` cannot
    block the repo .env. Returns the path loaded, or None if no file was found.
    """
    env_path = path or Path(__file__).resolve().parents[2] / ".env"
    if not env_path.is_file():
        return None

    for raw_line in env_path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip()
        if not key:
            continue
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in {'"', "'"}:
            value = value[1:-1]
        existing = os.environ.get(key)
        if existing is None or not existing.strip():
            os.environ[key] = value
    return env_path
