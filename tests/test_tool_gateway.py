"""ToolGateway and fake Git/Docker handler tests."""

from __future__ import annotations

from pathlib import Path

import pytest

from murphy.mcp.fake_handlers.docker import docker_handler
from murphy.mcp.fake_handlers.git import git_handler
from murphy.mcp.tool_gateway import (
    ServerStatus,
    ToolGateway,
    load_mcp_config,
)
from murphy.policy.intent import SideEffect, build_validated_action_intent
from murphy.policy.schema import SchemaValidationError, load_schemas


@pytest.fixture
def project_root(tmp_path: Path) -> Path:
    root = tmp_path / "my-project"
    root.mkdir()
    return root


@pytest.fixture
def gateway() -> ToolGateway:
    gw = ToolGateway()
    gw.register_handler("git", git_handler)
    gw.register_handler("docker", docker_handler)
    gw.start()
    return gw


# --- config / schemas ---

def test_mcp_config_loads_checked_in_servers() -> None:
    config = load_mcp_config()
    assert config.version == 1
    assert set(config.servers) >= {"git", "docker", "wezterm", "cursor", "spotify"}
    assert config.servers["git"].transport.value == "stdio"
    assert config.servers["git"].command is None


def test_all_git_and_docker_schemas_exist() -> None:
    schemas = load_schemas()
    expected = {
        "git.status",
        "git.current_branch",
        "git.commit",
        "git.push",
        "docker.compose_up",
        "docker.compose_down",
        "docker.run_service",
        "docker.list_containers",
        "docker.prune",
    }
    assert expected <= set(schemas)


def test_run_service_requires_service_name(project_root: Path) -> None:
    with pytest.raises(SchemaValidationError):
        build_validated_action_intent(
            server="docker",
            tool="run_service",
            args={},
            project_root=project_root,
            side_effect=SideEffect.mutative,
        )


# --- ToolGateway lifecycle ---

def test_server_without_handler_is_unavailable_after_start() -> None:
    gw = ToolGateway()
    gw.register_handler("git", git_handler)
    gw.start()

    assert gw.status("git") == ServerStatus.available
    assert gw.status("docker") == ServerStatus.unavailable


def test_call_before_start_fails(project_root: Path) -> None:
    gw = ToolGateway()
    gw.register_handler("git", git_handler)
    intent = build_validated_action_intent(
        server="git",
        tool="status",
        args={},
        project_root=project_root,
        side_effect=SideEffect.read_only,
    )

    result = gw.call(intent)

    assert not result.ok
    assert "not_started" in (result.error or "")


def test_call_unavailable_server_does_not_run_handler(project_root: Path) -> None:
    gw = ToolGateway()
    gw.register_handler("git", git_handler)
    gw.start()
    # docker has no handler, so start() left it unavailable

    intent = build_validated_action_intent(
        server="docker",
        tool="compose_down",
        args={},
        project_root=project_root,
        side_effect=SideEffect.mutative,
    )
    result = gw.call(intent)

    assert not result.ok
    assert "unavailable" in (result.error or "")


# --- fake handler round-trips ---

def test_git_status_round_trip(gateway: ToolGateway, project_root: Path) -> None:
    intent = build_validated_action_intent(
        server="git",
        tool="status",
        args={},
        project_root=project_root,
        side_effect=SideEffect.read_only,
    )
    result = gateway.call(intent)

    assert result.ok
    assert result.intent_digest == intent.digest
    assert result.content == {"branch": "main", "clean": True}


def test_git_push_echoes_args(gateway: ToolGateway, project_root: Path) -> None:
    intent = build_validated_action_intent(
        server="git",
        tool="push",
        args={"remote": "origin", "branch": "feature/login", "force": False},
        project_root=project_root,
        side_effect=SideEffect.mutative,
    )
    result = gateway.call(intent)

    assert result.ok
    assert result.content == {
        "remote": "origin",
        "branch": "feature/login",
        "force": False,
        "pushed": True,
    }


def test_docker_compose_up_round_trip(gateway: ToolGateway, project_root: Path) -> None:
    intent = build_validated_action_intent(
        server="docker",
        tool="compose_up",
        args={"services": ["postgres"]},
        project_root=project_root,
        side_effect=SideEffect.additive,
    )
    result = gateway.call(intent)

    assert result.ok
    assert result.content == {"services": ["postgres"], "up": True}


def test_docker_run_service_round_trip(gateway: ToolGateway, project_root: Path) -> None:
    intent = build_validated_action_intent(
        server="docker",
        tool="run_service",
        args={"service": "api", "command": "pytest"},
        project_root=project_root,
        side_effect=SideEffect.mutative,
    )
    result = gateway.call(intent)

    assert result.ok
    assert result.content == {
        "service": "api",
        "command": "pytest",
        "ran": True,
    }


def test_unknown_git_tool_returns_tool_error(
    gateway: ToolGateway,
    project_root: Path,
) -> None:
    # Bypass schema so the fake handler sees an unsupported tool name
    from murphy.policy.intent import build_action_intent

    intent = build_action_intent(
        server="git",
        tool="rebase",
        args={},
        project_root=project_root,
        side_effect=SideEffect.mutative,
    )
    result = gateway.call(intent)

    assert not result.ok
    assert "Unknown git tool" in (result.error or "")
    assert gateway.status("git") == ServerStatus.unavailable
