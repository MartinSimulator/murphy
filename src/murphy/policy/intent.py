"""
Intent.py is a module that defines the intent model (i.e. the action to be taken by Murphy) for a given user request.
An ActionIntent describes the proposed action to be taken by Murphy only, not the result or confirmation of that action.
An ActionIntent is created when Murphy receives a user request and needs to determine the proposed action to take.
"""

from pathlib import Path
from pydantic import BaseModel, ConfigDict
from typing import Mapping, Any
from enum import Enum

# Define the possible side effects of an intent
class SideEffect(str, Enum):
    read_only = "read-only"
    additive = "additive"
    mutative = "mutative"
    destructive = "destructive"

# Define the intent model using Pydantic
class ActionIntent(BaseModel):
    model_config = ConfigDict(frozen=True)

    server: str # e.g. "git"
    tool: str # e.g. "push"
    args: Mapping[str, Any] # e.g. {"branch": "main"}
    project_root: Path # e.g. "/Users/johndoe/projects/my-project"
    side_effect: SideEffect # enum: "read-only", "additive", "mutative", "destructive"
    digest: str # sha256 of the canonical payload