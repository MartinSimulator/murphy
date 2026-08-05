"""Smoke tests for the package scaffold."""

from __future__ import annotations

from pathlib import Path

from murphy import __version__
from murphy.cli import main
from murphy.paths import USER_DATA_DIR


def test_version_is_set() -> None:
    assert __version__ == "0.1.0"


def test_user_data_dir_is_application_support() -> None:
    assert USER_DATA_DIR.name == "Murphy"
    assert "Application Support" in USER_DATA_DIR.parts


def test_cli_prints_help(capsys) -> None:
    assert main([]) == 0
    captured = capsys.readouterr()
    assert "murphy" in captured.out.lower()


def test_config_defaults_exist() -> None:
    root = Path(__file__).resolve().parents[1]
    assert (root / "config" / "policy.defaults.yaml").is_file()
    assert (root / "config" / "mcp.servers.yaml").is_file()
