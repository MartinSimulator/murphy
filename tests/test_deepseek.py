"""DeepSeekClient: Anthropic-compatible Messages API via httpx (mocked)."""

from __future__ import annotations

import json

import httpx
import pytest

from murphy.orchestrator.config import LLMConfig
from murphy.orchestrator.deepseek import DeepSeekClient, _build_payload, _parse_response
from murphy.orchestrator.llm import (
    LLMRequest,
    LLMResponseError,
    LLMUnavailableError,
)


def _config() -> LLMConfig:
    return LLMConfig(
        base_url="https://api.deepseek.com/anthropic",
        model="deepseek-v4-flash",
        timeout_seconds=5.0,
        api_key_env="TEST_DEEPSEEK_KEY",
    )


def _request() -> LLMRequest:
    return LLMRequest(
        system="You are Murphy.",
        user="check git status",
        tools=[
            {
                "name": "git__status",
                "description": "git.status",
                "input_schema": {"type": "object", "properties": {}},
            }
        ],
    )


def test_build_payload_includes_tools_and_user() -> None:
    payload = _build_payload(_request(), model="deepseek-v4-flash")

    assert payload["model"] == "deepseek-v4-flash"
    assert payload["system"] == "You are Murphy."
    assert payload["messages"][-1] == {"role": "user", "content": "check git status"}
    assert payload["tools"][0]["name"] == "git__status"


def test_parse_response_tool_use_and_text() -> None:
    data = {
        "content": [
            {"type": "text", "text": "Checking status."},
            {
                "type": "tool_use",
                "id": "toolu_1",
                "name": "git__status",
                "input": {},
            },
            {"type": "thinking", "thinking": "reason..."},
        ]
    }

    parsed = _parse_response(data)

    assert parsed.text == "Checking status."
    assert len(parsed.tool_calls) == 1
    assert parsed.tool_calls[0].server == "git"
    assert parsed.tool_calls[0].tool == "status"
    assert "thinking_blocks" in parsed.provider_fields


def test_complete_success_with_mock_transport(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("TEST_DEEPSEEK_KEY", "test-key")

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path.endswith("/v1/messages")
        assert request.headers["x-api-key"] == "test-key"
        body = json.loads(request.content.decode())
        assert body["model"] == "deepseek-v4-flash"
        return httpx.Response(
            200,
            json={
                "content": [
                    {
                        "type": "tool_use",
                        "id": "1",
                        "name": "git__status",
                        "input": {},
                    }
                ]
            },
        )

    transport = httpx.MockTransport(handler)
    http_client = httpx.Client(transport=transport)
    client = DeepSeekClient(config=_config(), client=http_client)

    result = client.complete(_request())

    assert result.tool_calls[0].tool == "status"
    http_client.close()


def test_complete_missing_api_key(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("TEST_DEEPSEEK_KEY", raising=False)
    client = DeepSeekClient(config=_config(), client=httpx.Client())

    with pytest.raises(LLMUnavailableError, match="API key"):
        client.complete(_request())


def test_complete_http_500_is_unavailable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("TEST_DEEPSEEK_KEY", "test-key")

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(503, text="down")

    client = DeepSeekClient(
        config=_config(),
        client=httpx.Client(transport=httpx.MockTransport(handler)),
    )

    with pytest.raises(LLMUnavailableError, match="server error"):
        client.complete(_request())


def test_complete_http_400_is_response_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("TEST_DEEPSEEK_KEY", "test-key")

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            400,
            text=json.dumps(
                {
                    "error": {
                        "message": "tool_use ids were found without tool_result",
                        "type": "invalid_request_error",
                    }
                }
            ),
        )

    client = DeepSeekClient(
        config=_config(),
        client=httpx.Client(transport=httpx.MockTransport(handler)),
    )

    with pytest.raises(LLMResponseError, match="invalid_request_error: tool_use"):
        client.complete(_request())


def test_complete_invalid_api_key_is_unavailable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("TEST_DEEPSEEK_KEY", "test-key")

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            401,
            text=json.dumps(
                {
                    "error": {
                        "message": "Your api key: **** is invalid",
                        "type": "invalid_request_error",
                    }
                }
            ),
        )

    client = DeepSeekClient(
        config=_config(),
        client=httpx.Client(transport=httpx.MockTransport(handler)),
    )

    with pytest.raises(LLMUnavailableError, match="API key rejected"):
        client.complete(_request())


def test_parse_invalid_tool_name() -> None:
    with pytest.raises(LLMResponseError, match="invalid tool name"):
        _parse_response(
            {
                "content": [
                    {
                        "type": "tool_use",
                        "name": "git.status",
                        "input": {},
                    }
                ]
            }
        )
