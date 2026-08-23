# speech.py defines the SpeechOutput protocol, Null/Recording for tests/CLI, and KokoroSpeechOutput for production.

from __future__ import annotations

from pathlib import Path
from typing import Protocol

from murphy.paths import USER_DATA_DIR
from murphy.voice.config import TTSConfig, get_voice_config

# Checked-in names for the kokoro-onnx v1.0 release assets
_DEFAULT_MODEL_NAME = "kokoro-v1.0.onnx"
_DEFAULT_VOICES_NAME = "voices-v1.0.bin"


def default_kokoro_model_dir() -> Path:
    """ONNX + voices bin live under Application Support (not the git repo)."""
    return USER_DATA_DIR / "models" / "kokoro"


class SpeechOutput(Protocol):
    def speak(self, text: str) -> None:
        """Synthesize and play text synchronously (may be a no-op)."""
        ...


class NullSpeechOutput:
    """Silent stand-in for tests and CLI paths that must not open audio."""

    def speak(self, text: str) -> None:
        return


class RecordingSpeechOutput:
    """Test double that records spoken strings instead of playing audio."""

    def __init__(self) -> None:
        self.spoken: list[str] = []

    def speak(self, text: str) -> None:
        cleaned = text.strip()
        if cleaned:
            self.spoken.append(cleaned)


class KokoroSpeechOutput:
    """
    Local TTS via kokoro-onnx.

    Call warmup() once (from RuntimeController.start) so the first confirmation
    does not pay model-load cost mid-prompt. speak() is synchronous: synthesize
    then block on playback.
    """

    def __init__(
        self,
        *,
        voice: str | None = None,
        speed: float | None = None,
        lang: str | None = None,
        model_path: Path | None = None,
        voices_path: Path | None = None,
        config: TTSConfig | None = None,
    ) -> None:
        tts = config or get_voice_config().tts
        model_dir = default_kokoro_model_dir()
        if tts.model_dir:
            model_dir = Path(tts.model_dir).expanduser()

        self._voice = voice if voice is not None else tts.voice
        self._speed = speed if speed is not None else tts.speed
        self._lang = lang if lang is not None else tts.lang
        self._model_path = (
            model_path
            if model_path is not None
            else model_dir / _DEFAULT_MODEL_NAME
        )
        self._voices_path = (
            voices_path
            if voices_path is not None
            else model_dir / _DEFAULT_VOICES_NAME
        )
        self._kokoro = None
        self._warmed = False

    @property
    def voice(self) -> str:
        return self._voice

    @property
    def warmed(self) -> bool:
        return self._warmed

    @property
    def model_path(self) -> Path:
        return self._model_path

    @property
    def voices_path(self) -> Path:
        return self._voices_path

    def warmup(self) -> None:
        """Load the ONNX model once; raises if model files are missing."""
        if self._warmed:
            return
        self._ensure_engine()
        self._warmed = True

    def speak(self, text: str) -> None:
        """Synthesize text and play it through the default output device."""
        cleaned = text.strip()
        if not cleaned:
            return

        import sounddevice as sd

        engine = self._ensure_engine()
        samples, sample_rate = engine.create(
            cleaned,
            voice=self._voice,
            speed=self._speed,
            lang=self._lang,
        )
        sd.play(samples, sample_rate)
        sd.wait()
        self._warmed = True

    # ensure kokoro is initialized and ready to use
    def _ensure_engine(self):
        if self._kokoro is not None:
            return self._kokoro

        if not self._model_path.is_file():
            raise FileNotFoundError(
                f"Kokoro model not found at {self._model_path}. "
                "Download kokoro-v1.0.onnx into "
                f"{self._model_path.parent} (see docs/development-notes.md)."
            )
        if not self._voices_path.is_file():
            raise FileNotFoundError(
                f"Kokoro voices file not found at {self._voices_path}. "
                "Download voices-v1.0.bin into "
                f"{self._voices_path.parent} (see docs/development-notes.md)."
            )

        from kokoro_onnx import Kokoro

        self._kokoro = Kokoro(str(self._model_path), str(self._voices_path))
        return self._kokoro

# default speech output is kokoro
def default_speech_output() -> SpeechOutput:
    """Production TTS: Kokoro configured from voice.defaults.yaml."""
    return KokoroSpeechOutput()
