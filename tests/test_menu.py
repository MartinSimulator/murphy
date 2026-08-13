"""Tests for menu shell helpers and journal.fetch_recent (no live AppKit loop)."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

from murphy.audit.journal import AuditJournal
from murphy.cli import main
from murphy.policy.intent import SideEffect, build_validated_action_intent
from murphy.policy.gateway import (
    PolicyDecision,
    PolicyReason,
    PolicyTier,
)
from murphy.ui.log_viewer import format_recent_rows
from murphy.ui.menu_app import _state_title
from murphy.app.state import AppState


def test_state_title_covers_key_states() -> None:
    assert "Murphy" in _state_title(AppState.IDLE)
    assert "confirm" in _state_title(AppState.AWAITING_CONFIRMATION).lower()
    assert "degraded" in _state_title(AppState.DEGRADED).lower()


def test_fetch_recent_orders_newest_first(tmp_path: Path) -> None:
    journal = AuditJournal(db_path=tmp_path / "audit.db")
    root = tmp_path / "proj"
    root.mkdir()

    def record(tool: str) -> None:
        intent = build_validated_action_intent(
            server="git",
            tool=tool,
            args={},
            project_root=root,
            side_effect=SideEffect.read_only,
        )
        decision = PolicyDecision(
            tier=PolicyTier.auto_pass,
            reason_code=PolicyReason.tool_default,
            message=f"{tool} ok",
            intent_digest=intent.digest,
        )
        journal.record_proposal(intent, decision, outcome="executed")

    record("status")
    record("current_branch")
    rows = journal.fetch_recent(10)
    assert len(rows) == 2
    assert rows[0]["tool"] == "current_branch"
    assert rows[1]["tool"] == "status"
    assert "git.current_branch" in format_recent_rows(rows)
    journal.close()


def test_fetch_recent_rejects_bad_limit(tmp_path: Path) -> None:
    journal = AuditJournal(db_path=tmp_path / "audit.db")
    with pytest.raises(ValueError):
        journal.fetch_recent(0)
    journal.close()


def test_cli_menu_help_lists_command() -> None:
    assert main([]) == 0


@pytest.mark.skipif(sys.platform != "darwin", reason="PyObjC menu is macOS-only")
def test_menu_modules_import_on_macos() -> None:
    from murphy.ui import log_viewer, menu_app

    assert menu_app.MenuBarApp is not None
    assert log_viewer.LogViewerController is not None
