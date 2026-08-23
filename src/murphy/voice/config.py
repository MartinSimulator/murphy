# config.py loads checked-in voice defaults (STT/TTS) from voice.defaults.yaml.

from __future__ import annotations

from pathlib import Path

import yaml
from pydantic import BaseModel, ConfigDict, Field


class STTConfig(BaseModel):
    model_config = ConfigDict(frozen=True)

    provider: str = "mlx_whisper"
    model: str = "mlx-community/whisper-small-mlx"
    language: str = "en"
    sample_rate: int = Field(default=16000, ge=1)


class TTSConfig(BaseModel):
    model_config = ConfigDict(frozen=True)

    provider: str = "kokoro"
    voice: str = "af_heart"
    speed: float = Field(default=1.0, gt=0.0)
    lang: str = "en-us"
    # Optional override for the Application Support models/kokoro directory
    model_dir: str | None = None


class VoiceConfig(BaseModel):
    model_config = ConfigDict(frozen=True)

    version: int = 1
    stt: STTConfig = Field(default_factory=STTConfig)
    tts: TTSConfig = Field(default_factory=TTSConfig)


def _default_voice_config_path() -> Path:
    # src/murphy/voice/config.py -> repo root is parents[3]
    return Path(__file__).resolve().parents[3] / "config" / "voice.defaults.yaml"


def load_voice_config(path: Path | None = None) -> VoiceConfig:
    """Load checked-in voice defaults from YAML."""
    config_path = path or _default_voice_config_path()
    if not config_path.is_file():
        raise FileNotFoundError(f"voice config file not found: {config_path}")
    raw = yaml.safe_load(config_path.read_text(encoding="utf-8")) or {}
    return VoiceConfig.model_validate(raw)


_VOICE_CONFIG: VoiceConfig | None = None


def get_voice_config() -> VoiceConfig:
    """Return the cached voice config (loads once)."""
    global _VOICE_CONFIG
    if _VOICE_CONFIG is None:
        _VOICE_CONFIG = load_voice_config()
    return _VOICE_CONFIG
