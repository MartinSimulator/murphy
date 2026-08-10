"""Text facade (handle_text) wiring planner to executor."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from murphy.audit.journal import AuditJournal
from murphy.execution.confirmation import PendingConfirmation
from murphy.execution.executor import StepOutcome
from murphy.mcp.fake_handlers.docker import docker_handler
from murphy.mcp.fake_handlers.git import git_handler
from murphy.mcp.tool_gateway import ToolGateway
from murphy.orchestrator.fake_llm import FakeLLM
from murphy.orchestrator.llm import LLMResponse, ToolProposal
from murphy.orchestrator.router import handle_text
from murphy.policy.intent import ActionIntent


@pytest.fixture
def project_root(tmp_path: Path) -> Path:
    root = tmp_path / "repo"
    root.mkdir()
    return root


@pytest.fixture
def journal(tmp_path: Path) -> AuditJournal:
    return AuditJournal(db_path=tmp_path / "audit.db")


def _gateway() -> tuple[ToolGateway, list[str]]:
    calls: list[str] = []

    def track(server: str, handler):
        def wrapped(intent: ActionIntent) -> dict[str, Any]:
            calls.append(f"{server}.{intent.tool}")
            return handler(intent)

        return wrapped

    gw = ToolGateway()
    gw.register_handler("git", track("git", git_handler))
    gw.register_handler("docker", track("docker", docker_handler))
    gw.start()
    return gw, calls


def test_handle_text_auto_pass(project_root: Path, journal: AuditJournal) -> None:
    gw, calls = _gateway()
    llm = FakeLLM(
        exact={
            "check status": LLMResponse(
                tool_calls=[ToolProposal(server="git", tool="status", args={})],
            ),
        },
    )

    result = handle_text(
        "check status",
        project_root=project_root,
        llm=llm,
        gateway=gw,
        journal=journal,
        servers={"git"},
    )

    assert result.ok
    assert result.plan is not None
    assert result.plan.completed
    assert calls == ["git.status"]


def test_handle_text_llm_unavailable_calls_no_tools(
    project_root: Path, journal: AuditJournal
) -> None:
    gw, calls = _gateway()
    llm = FakeLLM(unavailable=True)

    result = handle_text(
        "anything",
        project_root=project_root,
        llm=llm,
        gateway=gw,
        journal=journal,
        servers={"git"},
    )

    assert not result.ok
    assert result.error == "llm_unavailable"
    assert result.plan is None
    assert calls == []


def test_handle_text_no_intents_returns_assistant_text(
    project_root: Path, journal: AuditJournal
) -> None:
    gw, calls = _gateway()
    llm = FakeLLM(
        default=LLMResponse(tool_calls=[], text="I can only orchestrate tools."),
    )

    result = handle_text(
        "tell me a joke",
        project_root=project_root,
        llm=llm,
        gateway=gw,
        journal=journal,
        servers={"git"},
    )

    assert result.ok
    assert result.assistant_text == "I can only orchestrate tools."
    assert calls == []


def test_handle_text_confirm_with_resolver(
    project_root: Path, journal: AuditJournal
) -> None:
    gw, calls = _gateway()
    llm = FakeLLM(
        default=LLMResponse(
            tool_calls=[
                ToolProposal(
                    server="git",
                    tool="push",
                    args={"remote": "origin", "branch": "main", "force": False},
                ),
            ],
        ),
    )

    def approve(pending: PendingConfirmation) -> str:
        return " ".join(pending.required_tokens)

    result = handle_text(
        "push to main",
        project_root=project_root,
        llm=llm,
        gateway=gw,
        journal=journal,
        resolve_confirmation=approve,
        servers={"git"},
    )

    assert result.ok
    assert calls == ["git.push"]
    assert result.plan is not None
    assert result.plan.completed
    assert result.plan.steps[-1].outcome == StepOutcome.executed
