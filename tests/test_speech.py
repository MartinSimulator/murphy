"""Tests for SpeechOutput helpers and KokoroSpeechOutput (mocked kokoro_onnx)."""

from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import MagicMock

import numpy as np
import pytest

from murphy.voice.config import load_voice_config
from murphy.voice.speech import (
    KokoroSpeechOutput,
    NullSpeechOutput,
    RecordingSpeechOutput,
    default_kokoro_model_dir,
)


@pytest.fixture
def mock_kokoro_stack(monkeypatch: pytest.MonkeyPatch) -> MagicMock:
    """Install fakes so tests never load ONNX or open the speaker."""
    mock_engine = MagicMock()
    mock_engine.create.return_value = (
        np.zeros(1600, dtype=np.float32),
        24000,
    )

    mock_mod = MagicMock()
    mock_mod.Kokoro.return_value = mock_engine
    monkeypatch.setitem(sys.modules, "kokoro_onnx", mock_mod)

    mock_sd = MagicMock()
    monkeypatch.setitem(sys.modules, "sounddevice", mock_sd)
    return mock_engine


def test_null_and_recording_speech() -> None:
    NullSpeechOutput().speak("ignored")
    recorder = RecordingSpeechOutput()
    recorder.speak("  hello  ")
    recorder.speak("   ")
    assert recorder.spoken == ["hello"]


def test_default_kokoro_model_dir_under_application_support() -> None:
    path = default_kokoro_model_dir()
    assert path.name == "kokoro"
    assert "Application Support" in path.parts
    assert path.parts[-2] == "models"


def test_kokoro_speak_calls_create_and_play(
    tmp_path: Path, mock_kokoro_stack: MagicMock
) -> None:
    model = tmp_path / "kokoro-v1.0.onnx"
    voices = tmp_path / "voices-v1.0.bin"
    model.write_bytes(b"model")
    voices.write_bytes(b"voices")

    import sounddevice as sd

    tts = KokoroSpeechOutput(
        voice="af_heart",
        speed=1.0,
        lang="en-us",
        model_path=model,
        voices_path=voices,
    )
    tts.speak("Plan completed.")

    mock_kokoro_stack.create.assert_called_once_with(
        "Plan completed.",
        voice="af_heart",
        speed=1.0,
        lang="en-us",
    )
    sd.play.assert_called_once()
    sd.wait.assert_called_once()
    assert tts.warmed is True


def test_kokoro_speak_skips_empty(
    tmp_path: Path, mock_kokoro_stack: MagicMock
) -> None:
    model = tmp_path / "kokoro-v1.0.onnx"
    voices = tmp_path / "voices-v1.0.bin"
    model.write_bytes(b"model")
    voices.write_bytes(b"voices")

    tts = KokoroSpeechOutput(model_path=model, voices_path=voices)
    tts.speak("   ")
    mock_kokoro_stack.create.assert_not_called()


def test_kokoro_warmup_requires_model_files(tmp_path: Path) -> None:
    tts = KokoroSpeechOutput(
        model_path=tmp_path / "missing.onnx",
        voices_path=tmp_path / "missing.bin",
    )
    with pytest.raises(FileNotFoundError, match="Kokoro model not found"):
        tts.warmup()


def test_kokoro_from_voice_config(tmp_path: Path) -> None:
    path = tmp_path / "voice.yaml"
    path.write_text(
        "version: 1\n"
        "stt:\n"
        "  provider: mlx_whisper\n"
        "  model: custom/model\n"
        "  language: en\n"
        "  sample_rate: 16000\n"
        "tts:\n"
        "  provider: kokoro\n"
        "  voice: af_bella\n"
        "  speed: 1.2\n"
        "  lang: en-us\n"
        f"  model_dir: {tmp_path / 'models'}\n",
        encoding="utf-8",
    )
    cfg = load_voice_config(path)
    tts = KokoroSpeechOutput(config=cfg.tts)
    assert tts.voice == "af_bella"
    assert tts.model_path == tmp_path / "models" / "kokoro-v1.0.onnx"
    assert tts.voices_path == tmp_path / "models" / "voices-v1.0.bin"
