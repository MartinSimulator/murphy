"""LLM config load and API key resolution."""

from __future__ import annotations

from pathlib import Path

import pytest

from murphy.orchestrator.config import (
    LLMConfig,
    load_llm_config,
    resolve_api_key,
)


def test_load_checked_in_llm_config() -> None:
    config = load_llm_config()

    assert config.provider == "deepseek"
    assert config.model == "deepseek-v4-flash"
    assert config.base_url.startswith("https://")
    assert config.max_tool_rounds == 2
    assert config.api_key_env == "DEEPSEEK_API_KEY"


def test_load_llm_config_from_custom_path(tmp_path: Path) -> None:
    path = tmp_path / "llm.defaults.yaml"
    path.write_text(
        "\n".join(
            [
                "version: 1",
                "provider: deepseek",
                "base_url: https://example.test",
                "model: deepseek-v4-flash",
                "timeout_seconds: 10",
                "max_tool_calls: 3",
                "api_key_env: MY_KEY",
            ]
        ),
        encoding="utf-8",
    )

    config = load_llm_config(path)

    assert config.base_url == "https://example.test"
    assert config.max_tool_rounds == 3
    assert config.api_key_env == "MY_KEY"


def test_resolve_api_key_reads_env(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    path = tmp_path / "llm.defaults.yaml"
    path.write_text(
        "\n".join(
            [
                "version: 1",
                "provider: deepseek",
                "base_url: https://example.test",
                "model: deepseek-v4-flash",
                "api_key_env: TEST_LLM_KEY",
            ]
        ),
        encoding="utf-8",
    )
    config = load_llm_config(path)
    monkeypatch.setenv("TEST_LLM_KEY", "secret-value")

    assert resolve_api_key(config) == "secret-value"


def test_resolve_api_key_missing_raises(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    path = tmp_path / "llm.defaults.yaml"
    path.write_text(
        "\n".join(
            [
                "version: 1",
                "provider: deepseek",
                "base_url: https://example.test",
                "model: deepseek-v4-flash",
                "api_key_env: MISSING_LLM_KEY",
            ]
        ),
        encoding="utf-8",
    )
    config = load_llm_config(path)
    monkeypatch.delenv("MISSING_LLM_KEY", raising=False)

    with pytest.raises(LookupError, match="MISSING_LLM_KEY"):
        resolve_api_key(config)


def test_llm_config_is_frozen() -> None:
    config = LLMConfig(
        base_url="https://example.test",
        model="deepseek-v4-flash",
    )
    with pytest.raises(Exception):
        config.model = "other"  # type: ignore[misc]
