"""Tests for voice config and MlxWhisperTranscriber (mocked mlx_whisper)."""

from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import MagicMock

import numpy as np
import pytest

from murphy.voice.config import VoiceConfig, get_voice_config, load_voice_config
from murphy.voice.stt import MlxWhisperTranscriber, NullTranscriber, StubTranscriber


@pytest.fixture
def mock_mlx_whisper(monkeypatch: pytest.MonkeyPatch) -> MagicMock:
    """Install a fake mlx_whisper module so tests never load real MLX."""
    mock_mod = MagicMock()
    mock_mod.transcribe = MagicMock(return_value={"text": ""})
    monkeypatch.setitem(sys.modules, "mlx_whisper", mock_mod)
    return mock_mod


def test_load_voice_defaults_from_repo() -> None:
    cfg = load_voice_config()
    assert cfg.stt.provider == "mlx_whisper"
    assert cfg.stt.model == "mlx-community/whisper-small-mlx"
    assert cfg.stt.language == "en"
    assert cfg.stt.sample_rate == 16000
    assert cfg.tts.voice == "af_heart"


def test_get_voice_config_caches(monkeypatch: pytest.MonkeyPatch) -> None:
    import murphy.voice.config as voice_config

    monkeypatch.setattr(voice_config, "_VOICE_CONFIG", None)
    first = get_voice_config()
    second = get_voice_config()
    assert first is second


def test_stub_and_null_transcribers() -> None:
    samples = np.ones(100, dtype=np.float32)
    assert NullTranscriber().transcribe(samples, 16000) == ""
    assert StubTranscriber("hello").transcribe(samples, 16000) == "hello"


def test_mlx_transcribe_empty_audio_skips_model(mock_mlx_whisper: MagicMock) -> None:
    stt = MlxWhisperTranscriber(model="test-model", language="en", sample_rate=16000)
    assert stt.transcribe(np.zeros(0, dtype=np.float32), 16000) == ""
    mock_mlx_whisper.transcribe.assert_not_called()


def test_mlx_transcribe_calls_mlx_whisper(mock_mlx_whisper: MagicMock) -> None:
    mock_mlx_whisper.transcribe.return_value = {"text": "  git status  "}

    stt = MlxWhisperTranscriber(model="test-model", language="en", sample_rate=16000)
    audio = np.linspace(-2.0, 2.0, 1600, dtype=np.float32)
    text = stt.transcribe(audio, 16000)

    assert text == "git status"
    mock_mlx_whisper.transcribe.assert_called_once()
    args, kwargs = mock_mlx_whisper.transcribe.call_args
    assert args[0].dtype == np.float32
    assert float(args[0].min()) >= -1.0
    assert float(args[0].max()) <= 1.0
    assert kwargs["path_or_hf_repo"] == "test-model"
    assert kwargs["language"] == "en"
    assert kwargs["verbose"] is False


def test_mlx_transcribe_rejects_wrong_sample_rate(mock_mlx_whisper: MagicMock) -> None:
    stt = MlxWhisperTranscriber(sample_rate=16000)
    with pytest.raises(ValueError, match="16000"):
        stt.transcribe(np.ones(10, dtype=np.float32), 44100)
    mock_mlx_whisper.transcribe.assert_not_called()


def test_mlx_warmup_loads_once(mock_mlx_whisper: MagicMock) -> None:
    mock_mlx_whisper.transcribe.return_value = {"text": ""}
    stt = MlxWhisperTranscriber(model="test-model", sample_rate=16000)
    assert stt.warmed is False
    stt.warmup()
    stt.warmup()
    assert stt.warmed is True
    assert mock_mlx_whisper.transcribe.call_count == 1


def test_mlx_from_voice_config(tmp_path: Path) -> None:
    path = tmp_path / "voice.yaml"
    path.write_text(
        "version: 1\n"
        "stt:\n"
        "  provider: mlx_whisper\n"
        "  model: custom/model\n"
        "  language: en\n"
        "  sample_rate: 16000\n"
        "tts:\n"
        "  voice: af_heart\n",
        encoding="utf-8",
    )
    cfg = load_voice_config(path)
    assert isinstance(cfg, VoiceConfig)
    stt = MlxWhisperTranscriber(config=cfg.stt)
    assert stt.model == "custom/model"
