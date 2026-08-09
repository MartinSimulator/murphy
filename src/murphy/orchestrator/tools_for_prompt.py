# tools_for_prompt.py builds the tool list sent to the LLM on each planning request.
# It formats checked-in JSON Schemas for the model; it does not validate or execute calls.
# Hard validation still happens later via build_validated_action_intent / schema.py.

from __future__ import annotations

from typing import Any

from murphy.mcp.tool_gateway import get_mcp_config
from murphy.policy.schema import get_schemas

# Separator used in prompt tool names: "git" + "__" + "push" -> "git__push"
# Avoids ambiguity if a tool name ever contains a dot.
_TOOL_NAME_SEP = "__"


def tool_name_for(server: str, tool: str) -> str:
    """Build the prompt-facing tool name the model should call."""
    return f"{server}{_TOOL_NAME_SEP}{tool}"


def parse_tool_name(name: str) -> tuple[str, str]:
    """Split a prompt tool name back into (server, tool)."""
    if _TOOL_NAME_SEP not in name:
        raise ValueError(f"invalid tool name (expected server__tool): {name!r}")
    server, tool = name.split(_TOOL_NAME_SEP, 1)
    if not server or not tool:
        raise ValueError(f"invalid tool name (empty server or tool): {name!r}")
    return server, tool


def _input_schema_for_prompt(schema: dict[str, Any]) -> dict[str, Any]:
    """Copy a checked-in JSON Schema into an Anthropic-style input_schema body."""
    # Drop meta keys the model does not need; keep validation shape intact.
    skip = {"$schema", "$id", "title"}
    return {key: value for key, value in schema.items() if key not in skip}


def _enabled_servers() -> set[str]:
    """Return MCP server names marked enabled in mcp.servers.yaml."""
    config = get_mcp_config()
    return {
        name
        for name, server in config.servers.items()
        if server.enabled
    }


def tools_for_prompt(*, servers: set[str] | None = None) -> list[dict[str, Any]]:
    """
    Return Anthropic-compatible tool definitions for LLMRequest.tools.

    By default includes schemas whose server is enabled in MCP config.
    Pass servers={...} to restrict further (e.g. only {"git", "docker"} in tests).
    """
    allowed = _enabled_servers() if servers is None else set(servers)
    schemas = get_schemas()
    tools: list[dict[str, Any]] = []

    for key in sorted(schemas):
        # Schema files are named "server.tool.json"; stem is "server.tool"
        if "." not in key:
            continue
        server, tool = key.split(".", 1)
        if server not in allowed:
            continue

        tools.append(
            {
                "name": tool_name_for(server, tool),
                "description": f"Murphy tool {key}",
                "input_schema": _input_schema_for_prompt(schemas[key]),
            }
        )

    return tools
