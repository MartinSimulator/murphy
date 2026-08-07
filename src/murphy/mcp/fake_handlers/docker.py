# Fake docker MCP handler for tests and local development.
# Registered on ToolGateway with register_handler("docker", docker_handler).
# Returns canned dicts - does not run real docker.

from __future__ import annotations

from typing import Any

from murphy.policy.intent import ActionIntent


def docker_handler(intent: ActionIntent) -> dict[str, Any]:
    if intent.tool == "compose_up":
        return {
            "services": list(intent.args.get("services", [])),
            "up": True,
        }

    if intent.tool == "compose_down":
        return {"down": True}

    if intent.tool == "run_service":
        return {
            "service": intent.args["service"],
            "command": intent.args.get("command"),
            "ran": True,
        }

    if intent.tool == "list_containers":
        return {
            "containers": [
                {"name": "postgres", "status": "running"},
                {"name": "api", "status": "running"},
            ],
        }

    if intent.tool == "prune":
        return {
            "all": intent.args["all"],
            "volumes": intent.args["volumes"],
            "pruned": True,
        }

    raise ValueError(f"Unknown docker tool: {intent.tool}")
