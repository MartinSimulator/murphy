"""Text E2E: FakeLLM → handle_text → policy/confirm → fake ToolGateway."""

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
from murphy.policy.gateway import PolicyReason
from murphy.policy.intent import ActionIntent
from murphy.policy.schema import get_schemas

@pytest.fixture
def project_root(tmp_path: Path) -> Path:
    root = tmp_path / "my-project"
    root.mkdir()
    return root

@pytest.fixture
def journal(tmp_path: Path) -> AuditJournal:
    return AuditJournal(db_path=tmp_path / "audit.db")

# _tracking_gateway is a fixture that returns a ToolGateway with a tracking handler for each tool.
def _tracking_gateway() -> tuple[ToolGateway, list[str]]:
    """Gateway with fakes that record every tool call as 'server.tool'."""
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

# _approve is a function that approves a pending confirmation by returning the required tokens.
def _approve(pending: PendingConfirmation) -> str:
    return " ".join(pending.required_tokens)

# multi-step auto-pass test
def test_e2e_llm_multi_step_auto_pass(
    project_root: Path, journal: AuditJournal
) -> None:
    gateway, calls = _tracking_gateway()
    llm = FakeLLM(
        default=LLMResponse(
            tool_calls=[
                ToolProposal(
                    server="docker",
                    tool="compose_up",
                    args={"services": ["postgres"]},
                ),
                ToolProposal(
                    server="docker",
                    tool="run_service",
                    args={"service": "api", "command": "pytest"},
                ),
            ],
        ),
    )

    result = handle_text(
        "spin up the test container and run tests",
        project_root=project_root,
        llm=llm,
        gateway=gateway,
        journal=journal,
        servers={"docker"},
    )

    assert result.ok
    assert result.plan is not None
    assert result.plan.completed
    assert calls == ["docker.compose_up", "docker.run_service"]
    assert all(step.outcome == StepOutcome.executed for step in result.plan.steps)


# confirm-required test
def test_e2e_confirm_required_grants_and_audits(
    project_root: Path, journal: AuditJournal
) -> None:
    gateway, calls = _tracking_gateway()
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

    result = handle_text(
        "push to main",
        project_root=project_root,
        llm=llm,
        gateway=gateway,
        journal=journal,
        resolve_confirmation=_approve,
        servers={"git"},
        session_id="e2e-confirm",
    )

    assert result.ok
    assert calls == ["git.push"]
    assert result.plan is not None
    digest = result.plan.steps[0].intent.digest
    outcomes = [row["outcome"] for row in journal.fetch_by_digest(digest)]
    assert StepOutcome.confirm_required.value in outcomes
    assert StepOutcome.confirmation_granted.value in outcomes
    assert StepOutcome.executed.value in outcomes

# confirm-required pauses without resolver test
def test_e2e_confirm_required_pauses_without_resolver(
    project_root: Path, journal: AuditJournal
) -> None:
    gateway, calls = _tracking_gateway()
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

    result = handle_text(
        "push to main",
        project_root=project_root,
        llm=llm,
        gateway=gateway,
        journal=journal,
        servers={"git"},
    )

    assert not result.ok
    assert calls == []
    assert result.plan is not None
    assert result.plan.pending is not None
    assert "confirm" in result.message.lower()


# hard deny test for path outside project
def test_e2e_hard_deny_out_of_project_path(
    project_root: Path,
    journal: AuditJournal,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Current git/docker schemas have no path args; inject a path-bearing schema
    # so the LLM→validate→classify path can still exercise hard deny.
    schemas = dict(get_schemas())
    schemas["cursor.open_project"] = {
        "type": "object",
        "additionalProperties": False,
        "required": ["path"],
        "properties": {"path": {"type": "string", "minLength": 1}},
    }
    monkeypatch.setattr("murphy.policy.schema._SCHEMAS", schemas)

    gateway, calls = _tracking_gateway()
    llm = FakeLLM(
        default=LLMResponse(
            tool_calls=[
                ToolProposal(
                    server="cursor",
                    tool="open_project",
                    args={"path": "/etc/passwd"},
                ),
            ],
        ),
    )

    result = handle_text(
        "open /etc/passwd in cursor",
        project_root=project_root,
        llm=llm,
        gateway=gateway,
        journal=journal,
        servers={"cursor"},
    )

    assert not result.ok
    assert calls == []
    assert result.plan is not None
    assert result.plan.stop_reason == StepOutcome.denied
    assert result.plan.steps[0].decision.reason_code == PolicyReason.deny_root


# schema rejection test for bad arguments
def test_e2e_schema_rejection_bad_args_calls_no_tools(
    project_root: Path, journal: AuditJournal
) -> None:
    gateway, calls = _tracking_gateway()
    llm = FakeLLM(
        default=LLMResponse(
            tool_calls=[
                ToolProposal(
                    server="git",
                    tool="push",
                    args={"remote": "origin"},  # missing branch and force
                ),
            ],
        ),
    )

    result = handle_text(
        "push please",
        project_root=project_root,
        llm=llm,
        gateway=gateway,
        journal=journal,
        servers={"git"},
    )

    assert not result.ok
    assert result.error == "plan_failed"
    assert result.plan is None
    assert calls == []

# schema rejection test for unknown tool
def test_e2e_schema_rejection_unknown_tool_calls_no_tools(
    project_root: Path, journal: AuditJournal
) -> None:
    gateway, calls = _tracking_gateway()
    llm = FakeLLM(
        default=LLMResponse(
            tool_calls=[
                ToolProposal(server="git", tool="rebase", args={}),
            ],
        ),
    )

    result = handle_text(
        "rebase onto main",
        project_root=project_root,
        llm=llm,
        gateway=gateway,
        journal=journal,
        servers={"git"},
    )

    assert not result.ok
    assert result.error == "plan_failed"
    assert calls == []


# LLM unavailable test
def test_e2e_llm_unavailable_fast_fail(
    project_root: Path, journal: AuditJournal
) -> None:
    gateway, calls = _tracking_gateway()
    llm = FakeLLM(unavailable=True)

    result = handle_text(
        "check git status",
        project_root=project_root,
        llm=llm,
        gateway=gateway,
        journal=journal,
        servers={"git"},
    )

    assert not result.ok
    assert result.error == "llm_unavailable"
    assert result.plan is None
    assert calls == []
    assert "unavailable" in result.message.lower()


# destructive prune requires action-bound phrase test
def test_e2e_destructive_prune_requires_action_bound_phrase(
    project_root: Path, journal: AuditJournal
) -> None:
    gateway, calls = _tracking_gateway()
    llm = FakeLLM(
        default=LLMResponse(
            tool_calls=[
                ToolProposal(
                    server="docker",
                    tool="prune",
                    args={"all": True, "volumes": True},
                ),
            ],
        ),
    )

    # Bare approval must not pass
    denied = handle_text(
        "prune everything",
        project_root=project_root,
        llm=llm,
        gateway=gateway,
        journal=journal,
        resolve_confirmation=lambda _pending: "yes",
        servers={"docker"},
    )
    assert not denied.ok
    assert calls == []

    # Action-bound tokens must pass
    granted = handle_text(
        "prune everything",
        project_root=project_root,
        llm=llm,
        gateway=gateway,
        journal=journal,
        resolve_confirmation=_approve,
        servers={"docker"},
    )
    assert granted.ok
    assert calls == ["docker.prune"]
    assert granted.plan is not None
    assert granted.plan.completed
