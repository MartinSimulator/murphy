# stt.py turns captured PCM into text.
# Null/Stub for tests; MlxWhisperTranscriber is the production Apple Silicon path.

from __future__ import annotations

from typing import Protocol

import numpy as np

from murphy.voice.config import STTConfig, get_voice_config


class Transcriber(Protocol):
    def transcribe(self, samples: np.ndarray, sample_rate: int) -> str:
        """Return plain text for the utterance (may be empty)."""
        ...


class NullTranscriber:
    """Placeholder that always returns empty text."""

    def transcribe(self, samples: np.ndarray, sample_rate: int) -> str:
        return ""


class StubTranscriber:
    """Test double that returns a fixed string regardless of audio."""

    def __init__(self, text: str) -> None:
        self._text = text

    def transcribe(self, samples: np.ndarray, sample_rate: int) -> str:
        return self._text


class MlxWhisperTranscriber:
    """
    Local STT via mlx-whisper on Apple Silicon.

    Call warmup() once (from RuntimeController.start) so the first real PTT
    does not pay model-download / load cost mid-utterance.
    """

    def __init__(
        self,
        *,
        model: str | None = None,
        language: str | None = None,
        sample_rate: int | None = None,
        config: STTConfig | None = None,
    ) -> None:
        stt = config or get_voice_config().stt
        self._model = model if model is not None else stt.model
        self._language = language if language is not None else stt.language
        self._sample_rate = (
            sample_rate if sample_rate is not None else stt.sample_rate
        )
        self._warmed = False

    @property
    def model(self) -> str:
        return self._model

    @property
    def warmed(self) -> bool:
        return self._warmed

    def warmup(self) -> None:
        """Load Whisper weights once using a short silent clip."""
        if self._warmed:
            return
        import mlx_whisper

        silence = np.zeros(self._sample_rate, dtype=np.float32)
        mlx_whisper.transcribe(
            silence,
            path_or_hf_repo=self._model,
            language=self._language,
            verbose=False,
        )
        self._warmed = True

    def transcribe(self, samples: np.ndarray, sample_rate: int) -> str:
        """Turn mono float32 PCM into plain text."""
        import mlx_whisper

        audio = np.asarray(samples, dtype=np.float32).reshape(-1)
        if audio.size == 0:
            return ""

        if sample_rate != self._sample_rate:
            raise ValueError(
                f"expected {self._sample_rate} Hz audio, got {sample_rate}"
            )

        audio = np.clip(audio, -1.0, 1.0)
        result = mlx_whisper.transcribe(
            audio,
            path_or_hf_repo=self._model,
            language=self._language,
            verbose=False,
        )
        return (result.get("text") or "").strip()


def default_transcriber() -> Transcriber:
    """Production STT: MLX Whisper configured from voice.defaults.yaml."""
    return MlxWhisperTranscriber()
