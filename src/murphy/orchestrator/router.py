# router.py is the text facade: one entry point from CLI/voice text to plan + execute.
# It does not talk to DeepSeek HTTP or MCP directly; those are injected.

from __future__ import annotations

from pathlib import Path

from pydantic import BaseModel, ConfigDict

from murphy.audit.journal import AuditJournal
from murphy.execution.confirmation import ConfirmationStore
from murphy.execution.executor import ConfirmationResolver, PlanResult, execute_actions
from murphy.mcp.tool_gateway import ToolGateway
from murphy.orchestrator.llm import LLMClient, LLMResponseError, LLMUnavailableError
from murphy.orchestrator.planner import PlanBuildError, plan


# Result returned to CLI / UI after handling one text request
class HandleResult(BaseModel):
    model_config = ConfigDict(frozen=True)

    ok: bool
    message: str
    plan: PlanResult | None = None
    assistant_text: str | None = None
    error: str | None = None


def _message_for_plan(result: PlanResult) -> str:
    """Build a short human summary from an executor PlanResult."""
    if result.completed:
        return "Plan completed."
    if result.pending is not None:
        return (
            "Confirmation required: "
            f"say something like '{result.pending.expected_phrase}'."
        )
    if result.stop_reason is not None:
        return f"Plan stopped: {result.stop_reason.value}."
    return "Plan did not complete."


def handle_text(
    text: str,
    *,
    project_root: Path,
    llm: LLMClient,
    gateway: ToolGateway,
    journal: AuditJournal,
    confirmations: ConfirmationStore | None = None,
    resolve_confirmation: ConfirmationResolver | None = None,
    servers: set[str] | None = None,
    session_id: str | None = None,
) -> HandleResult:
    """
    Plan the user text with the LLM, then run validated intents through the executor.

    On LLM/planning failure, return a HandleResult and do not call tools.
    """
    # Ask the planner for ActionIntents (may raise LLM or plan-build errors)
    try:
        # planned ActionIntents
        planned = plan(
            text,
            project_root=project_root,
            llm=llm,
            servers=servers,
        )
    except LLMUnavailableError as exc:
        # Cloud/model unreachable or API key missing: fail fast, no tools
        return HandleResult(
            ok=False,
            message="LLM is unavailable. Try again when DeepSeek is reachable.",
            error="llm_unavailable",
            assistant_text=str(exc) or None,
        )
    except (LLMResponseError, PlanBuildError) as exc:
        # Model replied unusably, or proposals failed schema validation
        return HandleResult(
            ok=False,
            message="Could not build a valid plan from the model response.",
            error="plan_failed",
            assistant_text=str(exc) or None,
        )

    # Model answered with narration only (no tools to run)
    if not planned.intents:
        return HandleResult(
            ok=True,
            message=planned.assistant_text or "No tools to run.",
            assistant_text=planned.assistant_text,
        )

    # Policy + confirmation + ToolGateway for each intent
    result = execute_actions(
        planned.intents,
        gateway,
        journal,
        confirmations=confirmations,
        resolve_confirmation=resolve_confirmation,
        session_id=session_id,
    )

    return HandleResult(
        ok=result.completed,
        message=_message_for_plan(result),
        plan=result,
        assistant_text=planned.assistant_text,
        error=None if result.completed else (result.stop_reason.value if result.stop_reason else "not_completed"),
    )
