"""Tests for optional .env loading."""

from __future__ import annotations

import os
from pathlib import Path

from murphy.env import load_dotenv


def test_load_dotenv_sets_missing_keys(tmp_path: Path, monkeypatch) -> None:
    env_file = tmp_path / ".env"
    env_file.write_text('FOO_TEST_KEY="bar"\n', encoding="utf-8")
    monkeypatch.delenv("FOO_TEST_KEY", raising=False)
    assert load_dotenv(env_file) == env_file
    assert os.environ["FOO_TEST_KEY"] == "bar"


def test_load_dotenv_replaces_empty_existing(tmp_path: Path, monkeypatch) -> None:
    env_file = tmp_path / ".env"
    env_file.write_text("FOO_TEST_KEY=from-file\n", encoding="utf-8")
    monkeypatch.setenv("FOO_TEST_KEY", "")
    load_dotenv(env_file)
    assert os.environ["FOO_TEST_KEY"] == "from-file"


def test_load_dotenv_does_not_override(tmp_path: Path, monkeypatch) -> None:
    env_file = tmp_path / ".env"
    env_file.write_text("FOO_TEST_KEY=from-file\n", encoding="utf-8")
    monkeypatch.setenv("FOO_TEST_KEY", "from-shell")
    load_dotenv(env_file)
    assert os.environ["FOO_TEST_KEY"] == "from-shell"
