# side_effects.py maps server.tool keys to SideEffect for intent construction.
# Orchestrator and workflows look up side effects here; they do not invent them.

from __future__ import annotations

from pathlib import Path

import yaml

# import the side effect enum from intent.py
from murphy.policy.intent import SideEffect


# default path to config/side_effects.yaml
def _default_side_effects_path() -> Path:
    return Path(__file__).resolve().parents[3] / "config" / "side_effects.yaml"


# load side_effects mapping from the YAML file
def load_side_effects(path: Path | None = None) -> dict[str, SideEffect]:
    # if no path is provided, use the default side_effects file
    config_path = path or _default_side_effects_path()
    if not config_path.is_file():
        raise FileNotFoundError(f"side_effects file not found: {config_path}")
    # load the side effects from the YAML file (or {} for falsy values ensure the function does nothing rather than blowing up)
    raw = yaml.safe_load(config_path.read_text(encoding="utf-8")) or {}
    entries = raw.get("side_effects") or {}
    if not isinstance(entries, dict):
        raise ValueError("side_effects.yaml: side_effects must be a mapping of tool keys to effects")
    return {str(key): SideEffect(value) for key, value in entries.items()}


# loaded side effects are cached in a global variable
_SIDE_EFFECTS: dict[str, SideEffect] | None = None


# get the cached side_effects
def get_side_effects() -> dict[str, SideEffect]:
    global _SIDE_EFFECTS
    if _SIDE_EFFECTS is None:
        _SIDE_EFFECTS = load_side_effects()
    return _SIDE_EFFECTS

# get the side effect for a given server.tool key
def side_effect_for(server: str, tool: str) -> SideEffect:
    """Return the configured SideEffect for server.tool."""
    key = f"{server}.{tool}"
    effects = get_side_effects()
    effect = effects.get(key)
    if effect is None:
        raise KeyError(f"unknown tool side effect: {key}")
    return effect
