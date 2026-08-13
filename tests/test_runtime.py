"""Tests for RuntimeController: worker-thread handle_text and confirmation."""

from __future__ import annotations

import threading
import time
from pathlib import Path

import pytest

from murphy.app.runtime import RuntimeController
from murphy.app.settings import save_project_root
from murphy.app.state import AppState
from murphy.audit.journal import AuditJournal
from murphy.mcp.fake_handlers.docker import docker_handler
from murphy.mcp.fake_handlers.git import git_handler
from murphy.mcp.tool_gateway import ToolGateway
from murphy.orchestrator.fake_llm import FakeLLM
from murphy.orchestrator.llm import LLMResponse, ToolProposal


@pytest.fixture
def project_root(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    root = tmp_path / "my-project"
    root.mkdir()
    settings_dir = tmp_path / "Murphy"
    settings_dir.mkdir()
    monkeypatch.setattr("murphy.app.settings.USER_DATA_DIR", settings_dir)
    monkeypatch.setattr(
        "murphy.app.settings._SETTINGS_FILE", settings_dir / "project_root.txt"
    )
    save_project_root(root)
    return root


@pytest.fixture
def journal(tmp_path: Path) -> AuditJournal:
    return AuditJournal(db_path=tmp_path / "audit.db")


def _gateway() -> ToolGateway:
    gw = ToolGateway()
    gw.register_handler("git", git_handler)
    gw.register_handler("docker", docker_handler)
    gw.start()
    return gw


def _wait_until(predicate, *, timeout: float = 2.0) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return
        time.sleep(0.01)
    raise AssertionError("condition not met before timeout")


def test_submit_text_runs_handle_text_off_calling_thread(
    project_root: Path, journal: AuditJournal
) -> None:
    caller = threading.get_ident()
    seen: dict[str, int] = {}

    class TrackingLLM(FakeLLM):
        def complete(self, request):  # type: ignore[no-untyped-def]
            seen["worker"] = threading.get_ident()
            return super().complete(request)

    llm = TrackingLLM(
        default=LLMResponse(
            tool_calls=[
                ToolProposal(
                    server="docker",
                    tool="compose_up",
                    args={"services": ["postgres"]},
                )
            ]
        )
    )
    runtime = RuntimeController(llm=llm, gateway=_gateway(), journal=journal)
    try:
        runtime.submit_text("spin up postgres")
        _wait_until(lambda: runtime.get_state() is AppState.IDLE)
        assert "worker" in seen
        assert seen["worker"] != caller
        assert "Plan completed" in runtime.status_message()
    finally:
        runtime.close()


def test_confirmation_phrase_unblocks_and_executes(
    project_root: Path, journal: AuditJournal
) -> None:
    llm = FakeLLM(
        default=LLMResponse(
            tool_calls=[
                ToolProposal(
                    server="git",
                    tool="push",
                    args={"remote": "origin", "branch": "main", "force": False},
                )
            ]
        )
    )
    runtime = RuntimeController(llm=llm, gateway=_gateway(), journal=journal)
    try:
        runtime.submit_text("push to main")
        _wait_until(
            lambda: runtime.get_state() is AppState.AWAITING_CONFIRMATION
        )
        pending = runtime.pending_confirmation()
        assert pending is not None
        runtime.submit_confirmation_phrase(" ".join(pending.required_tokens))
        _wait_until(lambda: runtime.get_state() is AppState.IDLE)
        assert "Plan completed" in runtime.status_message()
    finally:
        runtime.close()


def test_llm_unavailable_goes_degraded(
    project_root: Path, journal: AuditJournal
) -> None:
    runtime = RuntimeController(
        llm=FakeLLM(unavailable=True),
        gateway=_gateway(),
        journal=journal,
    )
    try:
        runtime.submit_text("do something")
        _wait_until(lambda: runtime.get_state() is AppState.DEGRADED)
        assert "unavailable" in runtime.status_message().lower()
    finally:
        runtime.close()


def test_submit_text_without_project_root_stays_idle(
    tmp_path: Path, journal: AuditJournal, monkeypatch: pytest.MonkeyPatch
) -> None:
    settings_dir = tmp_path / "Murphy"
    settings_dir.mkdir()
    monkeypatch.setattr("murphy.app.settings.USER_DATA_DIR", settings_dir)
    monkeypatch.setattr(
        "murphy.app.settings._SETTINGS_FILE", settings_dir / "project_root.txt"
    )
    runtime = RuntimeController(
        llm=FakeLLM(default=LLMResponse(text="hi")),
        gateway=_gateway(),
        journal=journal,
    )
    try:
        runtime.submit_text("hello")
        assert runtime.get_state() is AppState.IDLE
        assert "project root" in runtime.status_message().lower()
    finally:
        runtime.close()
