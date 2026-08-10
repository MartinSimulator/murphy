"""CLI ask subcommand smoke tests (no live DeepSeek)."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from murphy.cli import main
from murphy.orchestrator.router import HandleResult


def test_ask_help_lists_subcommand() -> None:
    with pytest.raises(SystemExit) as exc:
        main(["ask", "--help"])
    assert exc.value.code == 0


def test_ask_requires_project_root() -> None:
    with pytest.raises(SystemExit) as exc:
        main(["ask", "check status"])
    assert exc.value.code != 0


def test_ask_wires_handle_text(tmp_path: Path, capsys) -> None:
    root = tmp_path / "repo"
    root.mkdir()
    fake_result = HandleResult(ok=True, message="Plan completed.")

    with patch("murphy.execution.run_ask.handle_text", return_value=fake_result) as mocked:
        with patch("murphy.execution.run_ask.DeepSeekClient") as client_cls:
            with patch("murphy.execution.run_ask.AuditJournal") as journal_cls:
                client = MagicMock()
                client_cls.return_value = client
                journal = MagicMock()
                journal_cls.return_value = journal
                code = main(
                    [
                        "ask",
                        "check git status",
                        "--project-root",
                        str(root),
                    ]
                )

    assert code == 0
    mocked.assert_called_once()
    client.close.assert_called_once()
    journal.close.assert_called_once()
    assert "Plan completed." in capsys.readouterr().out
