# stt.py turns captured PCM into text.
# Deliverable 3 ships the protocol + a null/stub; MLX Whisper is Deliverable 4.

from __future__ import annotations

from typing import Protocol

import numpy as np


class Transcriber(Protocol):
    def transcribe(self, samples: np.ndarray, sample_rate: int) -> str:
        """Return plain text for the utterance (may be empty)."""
        ...


class NullTranscriber:
    """Placeholder until MLX Whisper is wired; always returns empty text."""

    def transcribe(self, samples: np.ndarray, sample_rate: int) -> str:
        return ""


class StubTranscriber:
    """Test double that returns a fixed string regardless of audio."""

    def __init__(self, text: str) -> None:
        self._text = text

    def transcribe(self, samples: np.ndarray, sample_rate: int) -> str:
        return self._text
