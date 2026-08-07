"""Policy decision-table tests for the three-tier gateway."""

from __future__ import annotations

import tempfile
from pathlib import Path

import pytest

from murphy.audit.journal import AuditJournal
from murphy.policy.gateway import (
    PolicyReason,
    PolicyTier,
    classify,
)
from murphy.policy.intent import SideEffect, build_action_intent, build_validated_action_intent
from murphy.policy.schema import SchemaValidationError


@pytest.fixture
def project_root(tmp_path: Path) -> Path:
    """A fake project directory used as the active Murphy project root."""
    root = tmp_path / "my-project"
    root.mkdir()
    return root

# Test that git status auto-passes
def test_git_status_auto_passes(project_root: Path) -> None:
    intent = build_action_intent(
        server="git",
        tool="status",
        args={},
        project_root=project_root,
        side_effect=SideEffect.read_only,
    )
    decision = classify(intent)

    assert decision.tier == PolicyTier.auto_pass
    assert decision.reason_code == PolicyReason.tool_default
    assert decision.intent_digest == intent.digest


# Test that feature branch pushes auto-pass
def test_feature_branch_push_auto_passes(project_root: Path) -> None:
    intent = build_validated_action_intent(
        server="git",
        tool="push",
        args={"remote": "origin", "branch": "feature/login", "force": False},
        project_root=project_root,
        side_effect=SideEffect.mutative,
    )
    decision = classify(intent)

    assert decision.tier == PolicyTier.auto_pass
    assert decision.reason_code == PolicyReason.tool_default


# Test that push to main requires confirmation
def test_push_to_main_requires_confirmation(project_root: Path) -> None:
    intent = build_validated_action_intent(
        server="git",
        tool="push",
        args={"remote": "origin", "branch": "main", "force": False},
        project_root=project_root,
        side_effect=SideEffect.mutative,
    )
    decision = classify(intent)

    assert decision.tier == PolicyTier.confirm_required
    assert decision.reason_code == PolicyReason.protected_branch

# Test that push to master requires confirmation
def test_push_to_master_requires_confirmation(project_root: Path) -> None:
    intent = build_validated_action_intent(
        server="git",
        tool="push",
        args={"remote": "origin", "branch": "master", "force": False},
        project_root=project_root,
        side_effect=SideEffect.mutative,
    )
    decision = classify(intent)

    assert decision.tier == PolicyTier.confirm_required
    assert decision.reason_code == PolicyReason.protected_branch

# Test that force push requires confirmation
def test_force_push_requires_confirmation(project_root: Path) -> None:
    intent = build_validated_action_intent(
        server="git",
        tool="push",
        args={"remote": "origin", "branch": "feature/login", "force": True},
        project_root=project_root,
        side_effect=SideEffect.destructive,
    )
    decision = classify(intent)

    assert decision.tier == PolicyTier.confirm_required
    assert decision.reason_code == PolicyReason.force_push

# Test that docker prune requires confirmation
def test_docker_prune_requires_confirmation(project_root: Path) -> None:
    intent = build_validated_action_intent(
        server="docker",
        tool="prune",
        args={"all": True, "volumes": True},
        project_root=project_root,
        side_effect=SideEffect.destructive,
    )
    decision = classify(intent)

    assert decision.tier == PolicyTier.confirm_required
    assert decision.reason_code == PolicyReason.tool_default

# Test that docker compose up auto-passes
def test_docker_compose_up_auto_passes(project_root: Path) -> None:
    intent = build_validated_action_intent(
        server="docker",
        tool="compose_up",
        args={"services": ["postgres"]},
        project_root=project_root,
        side_effect=SideEffect.additive,
    )
    decision = classify(intent)

    assert decision.tier == PolicyTier.auto_pass
    assert decision.reason_code == PolicyReason.tool_default

# Test that path outside project is denied
def test_path_outside_project_is_denied(project_root: Path) -> None:
    intent = build_action_intent(
        server="cursor",
        tool="open_project",
        args={"path": "/tmp/some-other-project"},
        project_root=project_root,
        side_effect=SideEffect.additive,
    )
    decision = classify(intent)

    assert decision.tier == PolicyTier.deny
    assert decision.reason_code == PolicyReason.out_of_project

# Test that /etc/passwd is denied
def test_etc_path_is_denied(project_root: Path) -> None:
    intent = build_action_intent(
        server="cursor",
        tool="open_project",
        args={"path": "/etc/passwd"},
        project_root=project_root,
        side_effect=SideEffect.additive,
    )
    decision = classify(intent)

    assert decision.tier == PolicyTier.deny
    assert decision.reason_code == PolicyReason.deny_root

# Test that unknown tool is denied
def test_unknown_tool_is_denied(project_root: Path) -> None:
    intent = build_action_intent(
        server="git",
        tool="rebase",
        args={},
        project_root=project_root,
        side_effect=SideEffect.mutative,
    )
    decision = classify(intent)

    assert decision.tier == PolicyTier.deny
    assert decision.reason_code == PolicyReason.unknown_tool

# Test that invalid push args fail schema before policy
def test_invalid_push_args_fail_schema_before_policy(project_root: Path) -> None:
    with pytest.raises(SchemaValidationError):
        build_validated_action_intent(
            server="git",
            tool="push",
            args={"remote": "origin", "branch": "main"},  # missing force
            project_root=project_root,
            side_effect=SideEffect.mutative,
        )

# Test that validate, classify, and journal round trip
def test_validate_classify_and_journal_round_trip(project_root: Path) -> None:
    intent = build_validated_action_intent(
        server="git",
        tool="push",
        args={"remote": "origin", "branch": "main", "force": False},
        project_root=project_root,
        side_effect=SideEffect.mutative,
    )
    decision = classify(intent)

    with tempfile.TemporaryDirectory() as tmp:
        db_path = Path(tmp) / "audit.db"
        with AuditJournal(db_path) as journal:
            row_id = journal.record_proposal(intent, decision, session_id="test-session")
            rows = journal.fetch_by_digest(intent.digest)

    assert row_id == 1
    assert len(rows) == 1
    assert rows[0]["policy_tier"] == PolicyTier.confirm_required.value
    assert rows[0]["policy_reason"] == PolicyReason.protected_branch.value
    assert rows[0]["intent_digest"] == intent.digest
    assert rows[0]["session_id"] == "test-session"
