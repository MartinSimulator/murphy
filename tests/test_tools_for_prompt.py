"""tools_for_prompt: schema catalog → LLM tool definitions."""

from __future__ import annotations

import pytest

from murphy.orchestrator.tools_for_prompt import (
    parse_tool_name,
    tool_name_for,
    tools_for_prompt,
)


def test_tool_name_round_trip() -> None:
    assert tool_name_for("git", "push") == "git__push"
    assert parse_tool_name("git__push") == ("git", "push")
    assert parse_tool_name("docker__compose_up") == ("docker", "compose_up")


def test_parse_tool_name_rejects_bad_names() -> None:
    with pytest.raises(ValueError, match="invalid tool name"):
        parse_tool_name("git.push")
    with pytest.raises(ValueError, match="invalid tool name"):
        parse_tool_name("__push")


def test_tools_for_prompt_includes_git_and_docker_schemas() -> None:
    tools = tools_for_prompt(servers={"git", "docker"})
    names = {entry["name"] for entry in tools}

    assert "git__status" in names
    assert "git__push" in names
    assert "docker__prune" in names
    assert "docker__compose_up" in names


def test_tools_for_prompt_respects_server_filter() -> None:
    tools = tools_for_prompt(servers={"git"})
    names = {entry["name"] for entry in tools}

    assert names
    assert all(name.startswith("git__") for name in names)
    assert not any(name.startswith("docker__") for name in names)


def test_git_push_input_schema_shape() -> None:
    tools = tools_for_prompt(servers={"git"})
    push = next(entry for entry in tools if entry["name"] == "git__push")

    assert "$schema" not in push["input_schema"]
    assert push["input_schema"]["type"] == "object"
    assert set(push["input_schema"]["required"]) == {"remote", "branch", "force"}
