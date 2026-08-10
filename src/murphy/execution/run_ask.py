# run_ask.py wires CLI args into handle_text (gateway, journal, LLM, confirmation).

from __future__ import annotations

import argparse

from murphy.audit.journal import AuditJournal
from murphy.execution.confirmation import PendingConfirmation
from murphy.execution.executor import ConfirmationResolver
from murphy.mcp.fake_handlers.docker import docker_handler
from murphy.mcp.fake_handlers.git import git_handler
from murphy.mcp.tool_gateway import ToolGateway
from murphy.orchestrator.deepseek import DeepSeekClient
from murphy.orchestrator.router import handle_text


def _build_fake_gateway() -> ToolGateway:
    """ToolGateway with in-process git/docker fakes (real MCP comes later)."""
    gateway = ToolGateway()
    gateway.register_handler("git", git_handler)
    gateway.register_handler("docker", docker_handler)
    gateway.start()
    return gateway


def run_ask(args: argparse.Namespace) -> int:
    """Run one murphy ask request; return process exit code 0/1."""
    gateway = _build_fake_gateway()
    journal = AuditJournal()
    llm = DeepSeekClient()

    resolve_confirmation: ConfirmationResolver | None = None
    if args.confirm_phrase is not None:
        phrase = args.confirm_phrase

        def resolve(_pending: PendingConfirmation) -> str | None:
            return phrase

        resolve_confirmation = resolve

    try:
        result = handle_text(
            args.text,
            project_root=args.project_root,
            llm=llm,
            gateway=gateway,
            journal=journal,
            resolve_confirmation=resolve_confirmation,
            servers={"git", "docker"},
        )
    finally:
        llm.close()
        journal.close()

    print(result.message)
    if result.assistant_text and result.assistant_text != result.message:
        print(result.assistant_text)
    if result.plan is not None:
        for step in result.plan.steps:
            tool_key = f"{step.intent.server}.{step.intent.tool}"
            print(f"  - {tool_key}: {step.outcome.value}")

    return 0 if result.ok else 1
