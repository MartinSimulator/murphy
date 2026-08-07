"""Sequential executor tests: policy gating, ToolGateway dispatch, audit outcomes."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from murphy.audit.journal import AuditJournal
from murphy.execution.executor import StepOutcome, execute_actions
from murphy.mcp.fake_handlers.docker import docker_handler
from murphy.mcp.fake_handlers.git import git_handler
from murphy.mcp.tool_gateway import ToolGateway
from murphy.policy.intent import ActionIntent, SideEffect, build_validated_action_intent


@pytest.fixture
def project_root(tmp_path: Path) -> Path:
    root = tmp_path / "my-project"
    root.mkdir()
    return root


@pytest.fixture
def journal(tmp_path: Path) -> AuditJournal:
    return AuditJournal(db_path=tmp_path / "audit.db")


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


def _status(project_root: Path) -> ActionIntent:
    return build_validated_action_intent(
        server="git",
        tool="status",
        args={},
        project_root=project_root,
        side_effect=SideEffect.read_only,
    )


def _feature_push(project_root: Path) -> ActionIntent:
    return build_validated_action_intent(
        server="git",
        tool="push",
        args={"remote": "origin", "branch": "feature/login", "force": False},
        project_root=project_root,
        side_effect=SideEffect.mutative,
    )


def _main_push(project_root: Path) -> ActionIntent:
    return build_validated_action_intent(
        server="git",
        tool="push",
        args={"remote": "origin", "branch": "main", "force": False},
        project_root=project_root,
        side_effect=SideEffect.mutative,
    )


def _compose_up(project_root: Path) -> ActionIntent:
    return build_validated_action_intent(
        server="docker",
        tool="compose_up",
        args={"services": ["postgres"]},
        project_root=project_root,
        side_effect=SideEffect.additive,
    )


def _prune(project_root: Path) -> ActionIntent:
    return build_validated_action_intent(
        server="docker",
        tool="prune",
        args={"all": True, "volumes": True},
        project_root=project_root,
        side_effect=SideEffect.destructive,
    )


def _denied_path(project_root: Path) -> ActionIntent:
    # cursor.open_project is in policy but path outside project hard-denies
    from murphy.policy.intent import build_action_intent

    return build_action_intent(
        server="cursor",
        tool="open_project",
        args={"path": "/etc/passwd"},
        project_root=project_root,
        side_effect=SideEffect.additive,
    )


# --- happy path ---

def test_all_auto_pass_actions_complete(
    project_root: Path,
    journal: AuditJournal,
) -> None:
    gateway, calls = _tracking_gateway()
    actions = [_status(project_root), _compose_up(project_root), _feature_push(project_root)]

    plan = execute_actions(actions, gateway, journal, session_id="s1")

    assert plan.completed
    assert plan.stop_reason is None
    assert len(plan.steps) == 3
    assert all(step.outcome == StepOutcome.executed for step in plan.steps)
    assert calls == ["git.status", "docker.compose_up", "git.push"]
    assert plan.steps[0].tool_result is not None
    assert plan.steps[0].tool_result.ok


# --- confirm_required stops the plan ---

def test_confirm_required_stops_and_skips_later_actions(
    project_root: Path,
    journal: AuditJournal,
) -> None:
    gateway, calls = _tracking_gateway()
    actions = [
        _status(project_root),
        _main_push(project_root),  # confirm_required
        _compose_up(project_root),  # must never run
    ]

    plan = execute_actions(actions, gateway, journal)

    assert not plan.completed
    assert plan.stop_reason == StepOutcome.confirm_required
    assert len(plan.steps) == 2
    assert plan.steps[0].outcome == StepOutcome.executed
    assert plan.steps[1].outcome == StepOutcome.confirm_required
    assert plan.steps[1].tool_result is None
    assert calls == ["git.status"]  # push and compose_up never dispatched


def test_docker_prune_stops_without_calling_handler(
    project_root: Path,
    journal: AuditJournal,
) -> None:
    gateway, calls = _tracking_gateway()

    plan = execute_actions([_prune(project_root)], gateway, journal)

    assert not plan.completed
    assert plan.stop_reason == StepOutcome.confirm_required
    assert calls == []


# --- deny stops the plan ---

def test_deny_stops_and_never_calls_tool(
    project_root: Path,
    journal: AuditJournal,
) -> None:
    gateway, calls = _tracking_gateway()
    actions = [
        _status(project_root),
        _denied_path(project_root),
        _feature_push(project_root),
    ]

    plan = execute_actions(actions, gateway, journal)

    assert not plan.completed
    assert plan.stop_reason == StepOutcome.denied
    assert len(plan.steps) == 2
    assert plan.steps[1].outcome == StepOutcome.denied
    assert calls == ["git.status"]


# --- tool failure stops the plan ---

def test_tool_error_stops_later_actions(
    project_root: Path,
    journal: AuditJournal,
) -> None:
    calls: list[str] = []

    def failing_git(intent: ActionIntent) -> dict[str, Any]:
        calls.append(f"git.{intent.tool}")
        if intent.tool == "status":
            raise RuntimeError("fake git crashed")
        return git_handler(intent)

    gateway = ToolGateway()
    gateway.register_handler("git", failing_git)
    gateway.register_handler("docker", docker_handler)
    gateway.start()

    actions = [_status(project_root), _compose_up(project_root)]
    plan = execute_actions(actions, gateway, journal)

    assert not plan.completed
    assert plan.stop_reason == StepOutcome.tool_error
    assert len(plan.steps) == 1
    assert plan.steps[0].outcome == StepOutcome.tool_error
    assert plan.steps[0].tool_result is not None
    assert not plan.steps[0].tool_result.ok
    assert calls == ["git.status"]


# --- audit journal ---

def test_executor_journals_outcomes(
    project_root: Path,
    journal: AuditJournal,
) -> None:
    gateway, _ = _tracking_gateway()
    status = _status(project_root)
    main_push = _main_push(project_root)

    plan = execute_actions([status, main_push], gateway, journal, session_id="audit-1")

    status_rows = journal.fetch_by_digest(status.digest)
    push_rows = journal.fetch_by_digest(main_push.digest)

    assert len(status_rows) == 1
    assert status_rows[0]["outcome"] == StepOutcome.executed.value
    assert status_rows[0]["session_id"] == "audit-1"

    assert len(push_rows) == 1
    assert push_rows[0]["outcome"] == StepOutcome.confirm_required.value
    assert plan.stop_reason == StepOutcome.confirm_required


def test_empty_plan_completes(journal: AuditJournal) -> None:
    gateway, calls = _tracking_gateway()

    plan = execute_actions([], gateway, journal)

    assert plan.completed
    assert plan.steps == []
    assert plan.stop_reason is None
    assert calls == []
