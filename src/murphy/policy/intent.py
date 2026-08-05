"""
Intent.py is a module that defines the intent model (i.e. the action to be taken by Murphy) for a given user request.
An ActionIntent describes the proposed action to be taken by Murphy only, not the result or confirmation of that action.
An ActionIntent is created when Murphy receives a user request and needs to determine the proposed action to take.
"""

from __future__ import annotations

import hashlib
import json
from enum import Enum
from pathlib import Path
from types import MappingProxyType
from typing import Any, Mapping

from pydantic import BaseModel, ConfigDict, computed_field, field_validator

# Define the possible side effects of an intent
class SideEffect(str, Enum):
    read_only = "read-only"
    additive = "additive"
    mutative = "mutative"
    destructive = "destructive"

# Helper function to convert values into a JSON-stable form with sorted object keys
# This is used to ensure that the digest of the action intent is the same for same actions regardless of argument order (like an equals operator)
def _json_ready(value: Any) -> Any:
    """Convert values into a JSON-stable form with sorted object keys."""
    if isinstance(value, Path):
        return str(value.expanduser().resolve())
    if isinstance(value, Mapping):
        return {
            str(key): _json_ready(item)
            for key, item in sorted(value.items(), key=lambda pair: str(pair[0]))
        }
    if isinstance(value, (list, tuple)):
        return [_json_ready(item) for item in value]
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    return str(value)

# Deep-freeze mappings/lists so args cannot be mutated after the intent is built
# (a mutable args dict would let callers change the action without changing digest)
def _freeze(value: Any) -> Any:
    if isinstance(value, Mapping):
        return MappingProxyType({str(key): _freeze(item) for key, item in value.items()})
    if isinstance(value, list):
        return tuple(_freeze(item) for item in value)
    return value

# Function to return the UTF-8 canonical bytes used for digesting an action
# UTF-8 is the encoding used to turn the JSON payload into bytes
def canonical_payload(
    server: str,
    tool: str,
    args: Mapping[str, Any],
    project_root: Path | str,
    side_effect: SideEffect,
) -> bytes:
    """Return the UTF-8 canonical bytes used for digesting an action."""
    payload = {
        "args": _json_ready(args),
        "project_root": str(Path(project_root).expanduser().resolve()),
        "server": server,
        "side_effect": side_effect.value,
        "tool": tool,
    }
    return json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    ).encode("utf-8")

# Function to return the SHA-256 hex digest of the canonical action payload
# SHA-256 is the hash function used to compare the canonical payload of two actions allowing for fast comparison of action identity without having to compare the entire payload
def digest_for(
    server: str,
    tool: str,
    args: Mapping[str, Any],
    project_root: Path | str,
    side_effect: SideEffect,
) -> str:
    """Return the SHA-256 hex digest of the canonical action payload."""
    return hashlib.sha256(
        canonical_payload(server, tool, args, project_root, side_effect)
    ).hexdigest()

# Define the intent model using Pydantic
# Notes: 
#   - @field_validator registers a function Pydantic runs while building the model to validate the field
#   - @computed_field is a property derived from the other fields whenever you access intent.digest
class ActionIntent(BaseModel):
    model_config = ConfigDict(
        frozen=True,
        arbitrary_types_allowed=True,
        extra="forbid",  # reject caller-supplied digest or other unknown fields
    )

    server: str # e.g. "git"
    tool: str # e.g. "push"
    args: Mapping[str, Any] # e.g. {"branch": "main"}  (stored immutable)
    project_root: Path # e.g. "/Users/johndoe/projects/my-project"
    side_effect: SideEffect # enum: "read-only", "additive", "mutative", "destructive"

    # Freeze the args mapping to ensure it is immutable after the intent is built
    @field_validator("args", mode="after")
    @classmethod
    def _freeze_args(cls, value: Mapping[str, Any]) -> Mapping[str, Any]:
        canonical = _json_ready(value)
        if not isinstance(canonical, dict):
            raise TypeError("args must be a mapping")
        return _freeze(canonical)

    # Resolve the project root to its absolute path
    @field_validator("project_root", mode="after")
    @classmethod
    def _resolve_project_root(cls, value: Path) -> Path:
        return value.expanduser().resolve()

    # digest is the SHA-256 of the payload (content fingerprint); always derived, never caller-supplied
    @computed_field  # type: ignore[prop-decorator]
    @property
    def digest(self) -> str:
        return digest_for(
            self.server,
            self.tool,
            self.args,
            self.project_root,
            self.side_effect,
        )

# Function to build an immutable ActionIntent with a digest bound to its canonical fields
def build_action_intent(
    *, # * indicates that the following parameters are keyword-only (e.g. server="git", tool="push", etc.)
    server: str,
    tool: str,
    args: Mapping[str, Any],
    project_root: Path | str,
    side_effect: SideEffect,
) -> ActionIntent:
    """Build an immutable ActionIntent with a digest bound to its canonical fields."""
    return ActionIntent(
        server=server,
        tool=tool,
        args=args,
        project_root=Path(project_root),
        side_effect=side_effect,
    )
