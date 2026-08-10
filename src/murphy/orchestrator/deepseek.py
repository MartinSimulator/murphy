# deepseek.py implements LLMClient against DeepSeek's Anthropic-compatible Messages API.
# Planner depends only on LLMClient.complete; all HTTP details stay in this file.

from __future__ import annotations

from typing import Any, Mapping

import httpx # HTTP library for making API requests

from murphy.orchestrator.config import LLMConfig, get_llm_config, resolve_api_key
from murphy.orchestrator.llm import (
    LLMRequest,
    LLMResponse,
    LLMResponseError,
    LLMUnavailableError,
    ToolProposal,
)
from murphy.orchestrator.tools_for_prompt import parse_tool_name

# Anthropic Messages API version header (DeepSeek documents it as ignored but clients send it)
_ANTHROPIC_VERSION = "2023-06-01"


class DeepSeekClient:
    """LLMClient for DeepSeek V4 Flash (Anthropic-compatible /v1/messages)."""

    def __init__(
        self,
        config: LLMConfig | None = None,
        *,
        client: httpx.Client | None = None, # if no client, create a new one
    ) -> None:
        self._config = config or get_llm_config()
        self._owns_client = client is None # if we own the client, close it when we're done
        self._client = client or httpx.Client(timeout=self._config.timeout_seconds)

    # close the client if we own it
    def close(self) -> None:
        if self._owns_client:
            self._client.close()

    # enter the context manager
    def __enter__(self) -> DeepSeekClient:
        return self

    # exit the context manager
    def __exit__(self, *args: object) -> None:
        self.close()


    def complete(self, request: LLMRequest) -> LLMResponse:
        # resolve the API key
        try:
            api_key = resolve_api_key(self._config)
        except LookupError as exc:
            raise LLMUnavailableError(str(exc)) from exc

        # build the URL
        url = f"{self._config.base_url.rstrip('/')}/v1/messages"

        # build the payload
        payload = _build_payload(request, model=self._config.model)
        headers = {
            "content-type": "application/json",
            "x-api-key": api_key,
            "anthropic-version": _ANTHROPIC_VERSION,
        }

        # make the request
        try:
            response = self._client.post(url, headers=headers, json=payload)
        except httpx.TimeoutException as exc:
            raise LLMUnavailableError("DeepSeek request timed out") from exc
        except httpx.HTTPError as exc:
            raise LLMUnavailableError(f"DeepSeek request failed: {exc}") from exc

        # handle the response
        if response.status_code >= 500:
            raise LLMUnavailableError(
                f"DeepSeek server error: HTTP {response.status_code}"
            )
        if response.status_code >= 400:
            raise LLMResponseError(
                f"DeepSeek rejected request: HTTP {response.status_code}: {response.text}"
            )

        # parse the response
        try:
            data = response.json()
        except ValueError as exc:
            raise LLMResponseError("DeepSeek returned non-JSON body") from exc

        return _parse_response(data)


# build the payload for the request
def _build_payload(request: LLMRequest, *, model: str) -> dict[str, Any]:
    """Convert Murphy LLMRequest into an Anthropic Messages API body."""
    messages: list[dict[str, Any]] = [dict(item) for item in request.messages] # convert the messages to a list of dictionaries
    messages.append({"role": "user", "content": request.user}) # add the user message
    payload: dict[str, Any] = { 
        "model": model,
        "max_tokens": 2048,
        "system": request.system,
        "messages": messages,
    }
    if request.tools: # if there are tools, add them to the payload
        payload["tools"] = [dict(tool) for tool in request.tools]
    return payload # return the payload


# parse the response from the API
def _parse_response(data: Mapping[str, Any] | Any) -> LLMResponse:
    """Convert Anthropic Messages JSON into Murphy LLMResponse."""
    if not isinstance(data, dict):
        raise LLMResponseError("DeepSeek response root must be an object")

    # get the content
    content = data.get("content")
    if content is None:
        raise LLMResponseError("DeepSeek response missing content")
    if not isinstance(content, list):
        raise LLMResponseError("DeepSeek content must be a list")

    # initialize the lists
    text_parts: list[str] = []
    tool_calls: list[ToolProposal] = []
    thinking_blocks: list[Any] = []

    # loop through the content and parse the blocks
    for block in content:
        if not isinstance(block, dict):
            continue
        block_type = block.get("type")
        if block_type == "text":
            text = block.get("text")
            if isinstance(text, str) and text:
                text_parts.append(text)
        elif block_type == "tool_use":
            name = block.get("name")
            raw_input = block.get("input") or {}
            if not isinstance(name, str):
                raise LLMResponseError("tool_use block missing name")
            if not isinstance(raw_input, dict):
                raise LLMResponseError(f"tool_use input must be an object: {name}")
            try:
                server, tool = parse_tool_name(name)
            except ValueError as exc:
                raise LLMResponseError(str(exc)) from exc
            tool_calls.append(
                ToolProposal(server=server, tool=tool, args=raw_input)
            )
        elif block_type in {"thinking", "redacted_thinking"}:
            thinking_blocks.append(block)

    provider_fields: dict[str, Any] = {}
    if thinking_blocks:
        provider_fields["thinking_blocks"] = thinking_blocks
    # return the response
    return LLMResponse(
        tool_calls=tool_calls,
        text="\n".join(text_parts) if text_parts else None,
        provider_fields=provider_fields,
    )
