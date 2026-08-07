# Fake git MCP handler for tests and local development.
# Registered on ToolGateway with register_handler("git", git_handler).
# Returns canned dicts - does not run real git.

from __future__ import annotations

from typing import Any

from murphy.policy.intent import ActionIntent


def git_handler(intent: ActionIntent) -> dict[str, Any]:
    if intent.tool == "status":
        return {"branch": "main", "clean": True}

    if intent.tool == "current_branch":
        return {"branch": "main"}

    if intent.tool == "commit":
        return {
            "message": intent.args["message"],
            "committed": True,
        }

    if intent.tool == "push":
        return {
            "remote": intent.args["remote"],
            "branch": intent.args["branch"],
            "force": intent.args["force"],
            "pushed": True,
        }

    raise ValueError(f"Unknown git tool: {intent.tool}")
