"""Smoke tests for the shared LLM contract in orchestrator.llm."""

from __future__ import annotations

from murphy.orchestrator.llm import (
    LLMClient,
    LLMRequest,
    LLMResponse,
    LLMResponseError,
    LLMUnavailableError,
    ToolProposal,
)


def test_tool_proposal_and_request_response_round_trip() -> None:
    proposal = ToolProposal(server="git", tool="status", args={})
    request = LLMRequest(
        system="You are Murphy.",
        user="check git status",
        tools=[{"name": "git.status", "input_schema": {"type": "object"}}],
    )
    response = LLMResponse(tool_calls=[proposal], text=None)

    assert request.user == "check git status"
    assert response.tool_calls[0].server == "git"
    assert response.tool_calls[0].tool == "status"


def test_llm_client_protocol_accepts_simple_implementation() -> None:
    class StubLLM:
        def complete(self, request: LLMRequest) -> LLMResponse:
            return LLMResponse(
                tool_calls=[
                    ToolProposal(server="git", tool="status", args={}),
                ],
                text=f"echo:{request.user}",
            )

    client: LLMClient = StubLLM()
    result = client.complete(
        LLMRequest(system="sys", user="hi", tools=[]),
    )

    assert result.text == "echo:hi"
    assert len(result.tool_calls) == 1


def test_error_types_are_exceptions() -> None:
    assert issubclass(LLMUnavailableError, Exception)
    assert issubclass(LLMResponseError, Exception)
