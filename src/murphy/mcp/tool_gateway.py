# tool_gateway.py is the sole choke point for MCP tool calls.
# Config describes stdio child-process servers; ToolGateway holds runtime session state.
# Policy and confirmation live upstream in the executor - this module only dispatches.

from __future__ import annotations

import time
from enum import Enum
from pathlib import Path
from typing import Any, Callable, Mapping

import yaml
from pydantic import BaseModel, ConfigDict, Field

from murphy.policy.intent import ActionIntent

# Handler signature for a single tool call (used by fakes and, later, real MCP sessions)
ToolHandler = Callable[[ActionIntent], Mapping[str, Any] | None]

# Transport used to talk to an MCP server (v1 is stdio only)
class MCPTransport(str, Enum):
    stdio = "stdio"

# Availability of one named server inside a running ToolGateway
class ServerStatus(str, Enum):
    not_started = "not_started"
    available = "available"
    unavailable = "unavailable"

# One entry under servers: in mcp.servers.yaml (name is the dict key, not a field)
class MCPServerConfig(BaseModel):
    model_config = ConfigDict(frozen=True)
    enabled: bool = True
    transport: MCPTransport = MCPTransport.stdio
    command: str | None = None
    args: list[str] = Field(default_factory=list)


# Frozen view of mcp.servers.yaml
# Created by load_mcp_config and cached in a global variable
class MCPConfig(BaseModel):
    model_config = ConfigDict(frozen=True)
    version: int = 1
    servers: dict[str, MCPServerConfig] = Field(default_factory=dict)


# Result of a single ToolGateway.call; frozen so callers cannot mutate what was recorded
class ToolResult(BaseModel):
    model_config = ConfigDict(frozen=True)
    server: str
    tool: str
    intent_digest: str
    ok: bool
    content: Mapping[str, Any] | None = None
    error: str | None = None
    elapsed_ms: int = 0


# default path to mcp.servers.yaml
def _default_mcp_path() -> Path:
    # src/murphy/mcp/tool_gateway.py -> repo root is parents[3]
    return Path(__file__).resolve().parents[3] / "config" / "mcp.servers.yaml"


# Load the MCP config from the given path defaulting to mcp.servers.yaml
def load_mcp_config(path: Path | None = None) -> MCPConfig:
    """Load checked-in MCP server defaults from YAML."""
    config_path = path or _default_mcp_path()
    raw = yaml.safe_load(config_path.read_text(encoding="utf-8")) or {}
    return MCPConfig.model_validate(raw)


# Cached MCP config; used when ToolGateway is constructed without an explicit config
_MCP_CONFIG: MCPConfig | None = None


def get_mcp_config() -> MCPConfig:
    global _MCP_CONFIG
    if _MCP_CONFIG is None:
        _MCP_CONFIG = load_mcp_config()
    return _MCP_CONFIG


# ToolGateway owns MCP dispatch. It is mutable on purpose (session status, handlers).
# It must not classify policy or collect confirmation - only call tools after the executor authorizes.
class ToolGateway:
    """Sole module allowed to invoke MCP tools (or test fakes registered in their place)."""

    def __init__(self, config: MCPConfig | None = None) -> None:
        # directory for mcp servers
        self.config = config or get_mcp_config()
        # status of each server
        self._status: dict[str, ServerStatus] = {
            name: ServerStatus.not_started for name in self.config.servers
        }
        # handlers for each server (empty for now but populated with real MCP sessions later)
        self._handlers: dict[str, ToolHandler] = {}

    # when someone asks to register a handler, we add it to the handlers dictionary
    def register_handler(self, server_name: str, handler: ToolHandler) -> None:
        if server_name not in self.config.servers:
            raise KeyError(f"Unknown MCP server '{server_name}'")
        self._handlers[server_name] = handler

    # Return the frozen config entry for a named server
    def get_server_config(self, server_name: str) -> MCPServerConfig:
        try:
            return self.config.servers[server_name]
        except KeyError as exc:
            raise KeyError(f"Unknown MCP server '{server_name}'") from exc

    # Return current availability for a named server
    def status(self, server_name: str) -> ServerStatus:
        if server_name not in self._status:
            raise KeyError(f"Unknown MCP server '{server_name}'")
        return self._status[server_name]

    # Go through each server in config and mark them as available if they have a handler
    def start(self) -> None:
        for name, server in self.config.servers.items():
            if not server.enabled:
                self._status[name] = ServerStatus.unavailable
                continue
            if name in self._handlers:
                self._status[name] = ServerStatus.available
                continue
            # Real stdio launch needs the MCP SDK and a non-null command; not wired yet
            self._status[name] = ServerStatus.unavailable

    # Clear the handlers dict and mark every server not_started
    def close(self) -> None:
        self._handlers.clear()
        for name in self._status:
            self._status[name] = ServerStatus.not_started

    # when someone wants to use the ToolGateway, we start the servers
    def __enter__(self) -> ToolGateway:
        self.start()
        return self

    # when someone is done using the ToolGateway, we stop the servers
    def __exit__(self, *args: object) -> None:
        self.close()

    # List configured server names (discovery of tool schemas comes later with the MCP SDK)
    def list_servers(self) -> list[str]:
        return sorted(self.config.servers)

    # Check if we know the server, if it's available, if there's a handler, and if so, call the handler
    def call(self, intent: ActionIntent) -> ToolResult:
        started = time.perf_counter()
        server_name = intent.server

        if server_name not in self.config.servers:
            return self._failure(
                intent,
                f"Unknown MCP server '{server_name}'",
                started,
            )

        if self._status.get(server_name) != ServerStatus.available:
            return self._failure(
                intent,
                f"MCP server '{server_name}' is {self._status.get(server_name, ServerStatus.not_started).value}",
                started,
            )

        handler = self._handlers.get(server_name)
        if handler is None:
            self._status[server_name] = ServerStatus.unavailable
            return self._failure(
                intent,
                f"MCP server '{server_name}' has no active session",
                started,
            )

        try:
            content = handler(intent)
        except Exception as exc:  # noqa: BLE001 - surface tool errors as ToolResult, mark unavailable
            self._status[server_name] = ServerStatus.unavailable
            return self._failure(intent, str(exc), started)

        elapsed_ms = int((time.perf_counter() - started) * 1000)
        return ToolResult(
            server=intent.server,
            tool=intent.tool,
            intent_digest=intent.digest,
            ok=True,
            content=dict(content) if content is not None else None,
            error=None,
            elapsed_ms=elapsed_ms,
        )

    # helper function to create a ToolResult for a failed tool call
    def _failure(
        self,
        intent: ActionIntent,
        error: str,
        started: float,
    ) -> ToolResult:
        elapsed_ms = int((time.perf_counter() - started) * 1000)
        return ToolResult(
            server=intent.server,
            tool=intent.tool,
            intent_digest=intent.digest,
            ok=False,
            content=None,
            error=error,
            elapsed_ms=elapsed_ms,
        )
