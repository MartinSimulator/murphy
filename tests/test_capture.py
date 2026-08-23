"""Tests for AudioCapture fakes and RuntimeController push-to-talk."""

from __future__ import annotations

import time
from pathlib import Path

import numpy as np
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
from murphy.voice.capture import CaptureResult, FakeAudioCapture
from murphy.voice.speech import NullSpeechOutput
from murphy.voice.stt import StubTranscriber


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


def test_fake_capture_returns_preset_samples() -> None:
    samples = np.ones(1600, dtype=np.float32)
    capture = FakeAudioCapture(samples=samples, sample_rate=16000)
    capture.start()
    result = capture.stop()
    assert isinstance(result, CaptureResult)
    assert not result.is_empty
    assert result.sample_rate == 16000
    assert len(result.samples) == 1600
    assert result.duration_seconds == pytest.approx(0.1)


def test_ptt_with_stub_stt_submits_text(
    project_root: Path, journal: AuditJournal
) -> None:
    llm = FakeLLM(
        default=LLMResponse(
            tool_calls=[
                ToolProposal(server="git", tool="status", args={}),
            ]
        )
    )
    runtime = RuntimeController(
        llm=llm,
        gateway=_gateway(),
        journal=journal,
        capture=FakeAudioCapture(samples=np.ones(800, dtype=np.float32)),
        transcriber=StubTranscriber("git status"),
        speech=NullSpeechOutput(),
    )
    try:
        runtime.begin_ptt()
        assert runtime.get_state() is AppState.LISTENING
        runtime.end_ptt()
        # Do not wait on IDLE alone: there is a brief IDLE between STT and planning
        _wait_until(lambda: "Plan completed" in runtime.status_message())
        assert runtime.get_state() is AppState.IDLE
    finally:
        runtime.close()


def test_ptt_empty_audio_returns_idle(
    project_root: Path, journal: AuditJournal
) -> None:
    runtime = RuntimeController(
        llm=FakeLLM(default=LLMResponse(text="hi")),
        gateway=_gateway(),
        journal=journal,
        capture=FakeAudioCapture(samples=np.zeros(0, dtype=np.float32)),
        transcriber=StubTranscriber("should not run meaningfully"),
        speech=NullSpeechOutput(),
    )
    try:
        runtime.begin_ptt()
        runtime.end_ptt()
        _wait_until(lambda: runtime.get_state() is AppState.IDLE)
        assert "audio" in runtime.status_message().lower() or "speech" in runtime.status_message().lower()
    finally:
        runtime.close()


def test_ptt_confirmation_phrase(
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
    # First ask via text to reach awaiting confirmation, then PTT for the phrase
    runtime = RuntimeController(
        llm=llm,
        gateway=_gateway(),
        journal=journal,
        capture=FakeAudioCapture(samples=np.ones(800, dtype=np.float32)),
        transcriber=StubTranscriber("confirm push"),
        speech=NullSpeechOutput(),
    )
    try:
        runtime.submit_text("push to main")
        _wait_until(
            lambda: runtime.get_state() is AppState.AWAITING_CONFIRMATION
        )
        runtime.begin_ptt()
        assert runtime.get_state() is AppState.LISTENING
        runtime.end_ptt()
        _wait_until(lambda: runtime.get_state() is AppState.IDLE)
        assert "Plan completed" in runtime.status_message()
    finally:
        runtime.close()
