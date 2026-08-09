"""FakeLLM: scripted LLMClient for tests."""

from __future__ import annotations

import pytest

from murphy.orchestrator.fake_llm import FakeLLM
from murphy.orchestrator.llm import (
    LLMClient,
    LLMRequest,
    LLMResponse,
    LLMResponseError,
    LLMUnavailableError,
    ToolProposal,
)


def _request(user: str) -> LLMRequest:
    return LLMRequest(system="sys", user=user, tools=[])


def _status_response() -> LLMResponse:
    return LLMResponse(
        tool_calls=[ToolProposal(server="git", tool="status", args={})],
    )


def test_fake_llm_satisfies_llm_client_protocol() -> None:
    client: LLMClient = FakeLLM(default=_status_response())
    result = client.complete(_request("anything"))
    assert len(result.tool_calls) == 1


def test_exact_match_wins() -> None:
    fake = FakeLLM(
        exact={
            "check git status": _status_response(),
        },
        contains={
            "git": LLMResponse(
                tool_calls=[
                    ToolProposal(server="git", tool="push", args={"branch": "main"}),
                ],
            ),
        },
    )

    result = fake.complete(_request("  Check  Git  Status "))

    assert result.tool_calls[0].tool == "status"
    assert len(fake.calls) == 1


def test_substring_match_when_no_exact() -> None:
    fake = FakeLLM(
        contains={
            "prune": LLMResponse(
                tool_calls=[
                    ToolProposal(
                        server="docker",
                        tool="prune",
                        args={"all": True, "volumes": True},
                    ),
                ],
            ),
        },
    )

    result = fake.complete(_request("please prune the docker mess"))

    assert result.tool_calls[0].server == "docker"
    assert result.tool_calls[0].tool == "prune"


def test_default_used_when_nothing_matches() -> None:
    fake = FakeLLM(default=_status_response())
    result = fake.complete(_request("unrelated utterance"))
    assert result.tool_calls[0].tool == "status"


def test_unscripted_user_text_raises() -> None:
    fake = FakeLLM()
    with pytest.raises(LLMResponseError, match="no fake response scripted"):
        fake.complete(_request("no script for this"))


def test_unavailable_raises() -> None:
    fake = FakeLLM(unavailable=True, default=_status_response())
    with pytest.raises(LLMUnavailableError, match="unavailable"):
        fake.complete(_request("check git status"))
    assert len(fake.calls) == 1
