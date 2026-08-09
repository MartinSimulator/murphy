# config.py loads and caches orchestrator LLM settings from llm.defaults.yaml.
# Secrets stay in the environment; the YAML only names which env var to read.

from __future__ import annotations

import os
from pathlib import Path

import yaml
from pydantic import BaseModel, ConfigDict, Field


# Frozen view of config/llm.defaults.yaml
class LLMConfig(BaseModel):
    model_config = ConfigDict(frozen=True)

    version: int = 1
    provider: str = "deepseek"
    base_url: str
    model: str
    timeout_seconds: float = 30.0
    max_tool_rounds: int = Field(default=2, ge=1)
    # Name of the env var that holds the API key (not the key itself)
    api_key_env: str = "DEEPSEEK_API_KEY"


# default path to config/llm.defaults.yaml
def _default_llm_config_path() -> Path:
    return Path(__file__).resolve().parents[3] / "config" / "llm.defaults.yaml"


# load llm config from the YAML file
def load_llm_config(path: Path | None = None) -> LLMConfig:
    config_path = path or _default_llm_config_path()
    if not config_path.is_file():
        raise FileNotFoundError(f"llm config file not found: {config_path}")
    raw = yaml.safe_load(config_path.read_text(encoding="utf-8")) or {}
    # Older draft used max_tool_calls; accept either key
    if "max_tool_rounds" not in raw and "max_tool_calls" in raw:
        raw = {**raw, "max_tool_rounds": raw["max_tool_calls"]}
    # Drop legacy api_key: ${...} if present; we resolve keys from the environment
    raw.pop("api_key", None)
    return LLMConfig.model_validate(raw)


# loaded llm config is cached in a global variable
_LLM_CONFIG: LLMConfig | None = None


# get the cached llm config
def get_llm_config() -> LLMConfig:
    global _LLM_CONFIG
    if _LLM_CONFIG is None:
        _LLM_CONFIG = load_llm_config()
    return _LLM_CONFIG


def resolve_api_key(config: LLMConfig | None = None) -> str:
    """Return the API key from the environment, or raise if missing."""
    cfg = config or get_llm_config()
    key = os.environ.get(cfg.api_key_env)
    if not key:
        raise LookupError(
            f"LLM API key not set; export {cfg.api_key_env} before calling DeepSeek"
        )
    return key
