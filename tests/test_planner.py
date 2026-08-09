"""Planner: LLM proposals → validated ActionIntents."""

from __future__ import annotations

from pathlib import Path

import pytest

from murphy.orchestrator.fake_llm import FakeLLM
from murphy.orchestrator.llm import LLMResponse, LLMUnavailableError, ToolProposal
from murphy.orchestrator.planner import PlanBuildError, plan
from murphy.policy.intent import SideEffect


@pytest.fixture
def project_root(tmp_path: Path) -> Path:
    root = tmp_path / "repo"
    root.mkdir()
    return root


def test_plan_builds_validated_intents(project_root: Path) -> None:
    fake = FakeLLM(
        exact={
            "check git status": LLMResponse(
                tool_calls=[
                    ToolProposal(server="git", tool="status", args={}),
                    ToolProposal(server="git", tool="current_branch", args={}),
                ],
            ),
        },
    )

    result = plan(
        "check git status",
        project_root=project_root,
        llm=fake,
        servers={"git"},
    )

    assert len(result.intents) == 2
    assert result.intents[0].server == "git"
    assert result.intents[0].tool == "status"
    assert result.intents[0].side_effect == SideEffect.read_only
    assert result.intents[1].tool == "current_branch"
    assert len(fake.calls) == 1


def test_plan_schema_failure_raises_plan_build_error(project_root: Path) -> None:
    fake = FakeLLM(
        default=LLMResponse(
            tool_calls=[
                ToolProposal(
                    server="git",
                    tool="push",
                    args={"remote": "origin"},  # missing branch/force
                ),
            ],
        ),
    )

    with pytest.raises(PlanBuildError, match="Failed to build intents"):
        plan(
            "push please",
            project_root=project_root,
            llm=fake,
            servers={"git"},
            max_tool_rounds=1,
        )


def test_plan_propagates_llm_unavailable(project_root: Path) -> None:
    fake = FakeLLM(unavailable=True)

    with pytest.raises(LLMUnavailableError):
        plan(
            "anything",
            project_root=project_root,
            llm=fake,
            servers={"git"},
        )


def test_plan_empty_tool_calls_returns_text_only(project_root: Path) -> None:
    fake = FakeLLM(
        default=LLMResponse(tool_calls=[], text="I cannot help with that."),
    )

    result = plan(
        "write a novel",
        project_root=project_root,
        llm=fake,
        servers={"git"},
    )

    assert result.intents == []
    assert result.assistant_text == "I cannot help with that."
