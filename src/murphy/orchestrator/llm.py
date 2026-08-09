# llm.py defines the shared LLM contract: request/response shapes and the client Protocol.
# deepseek.py and fake_llm.py implement LLMClient; planner.py depends only on this module.

from __future__ import annotations

from typing import Any, Mapping, Protocol

from pydantic import BaseModel, ConfigDict, Field


# One model-proposed tool call (not yet an ActionIntent; no side_effect or project_root)
class ToolProposal(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    server: str
    tool: str
    args: Mapping[str, Any] = Field(default_factory=dict)


# What the planner sends into an LLMClient.complete call
class LLMRequest(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    system: str
    user: str
    # Anthropic-style tool definitions built from checked-in JSON Schemas
    tools: list[Mapping[str, Any]] = Field(default_factory=list)
    # Prior turns (assistant/tool/reasoning) for multi-turn repair loops
    messages: list[Mapping[str, Any]] = Field(default_factory=list)


# What an LLMClient.complete call returns
class LLMResponse(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    tool_calls: list[ToolProposal] = Field(default_factory=list)
    # Optional assistant text (clarification, refusal, narration)
    text: str | None = None
    # Provider-specific fields (e.g. reasoning) to echo on the next turn
    provider_fields: Mapping[str, Any] = Field(default_factory=dict)


# Structural interface implemented by FakeLLM and the DeepSeek HTTP client
class LLMClient(Protocol):
    def complete(self, request: LLMRequest) -> LLMResponse:
        ...


# Timeout, HTTP failure, missing API key, or other transport problems
class LLMUnavailableError(Exception):
    """Raised when the LLM cannot be reached or is not configured."""


# Model returned something we cannot turn into tool proposals
class LLMResponseError(Exception):
    """Raised when the LLM response is malformed or unusable."""
