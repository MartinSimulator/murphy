# executor.py runs an ordered list of ActionIntents one at a time.
# auto_pass → ToolGateway; deny → stop; confirm_required → ConfirmationStore then wait/resolve.

from __future__ import annotations

from collections.abc import Callable
from enum import Enum

from pydantic import BaseModel, ConfigDict

from murphy.audit.journal import AuditJournal
from murphy.execution.confirmation import (
    ConfirmationStatus,
    ConfirmationStore,
    PendingConfirmation,
)
from murphy.mcp.tool_gateway import ToolGateway, ToolResult
from murphy.policy.gateway import PolicyDecision, PolicyTier, classify
from murphy.policy.intent import ActionIntent

# Callback returns an approval phrase, or None to deny the pending action
ConfirmationResolver = Callable[[PendingConfirmation], str | None]


# Why a single step finished (or why the plan stopped on it)
class StepOutcome(str, Enum):
    executed = "executed"
    denied = "denied"
    confirm_required = "confirm_required"
    confirmation_granted = "confirmation_granted"
    confirmation_denied = "confirmation_denied"
    tool_error = "tool_error"


# One step's policy decision plus optional tool call result
class StepResult(BaseModel):
    model_config = ConfigDict(frozen=True)
    intent: ActionIntent
    decision: PolicyDecision
    outcome: StepOutcome
    tool_result: ToolResult | None = None


# Result of running a whole plan; completed=False means later actions were not attempted
class PlanResult(BaseModel):
    model_config = ConfigDict(frozen=True)
    steps: list[StepResult]
    completed: bool
    stop_reason: StepOutcome | None = None
    # Set when the plan paused on confirm_required without a resolver answer
    pending: PendingConfirmation | None = None


def _dispatch_tool(
    action: ActionIntent,
    decision: PolicyDecision,
    gateway: ToolGateway,
    journal: AuditJournal,
    *,
    session_id: str | None,
) -> StepResult:
    """Call ToolGateway and journal executed or tool_error."""
    tool_result = gateway.call(action)
    if not tool_result.ok:
        journal.record_proposal(
            action,
            decision,
            session_id=session_id,
            outcome=StepOutcome.tool_error.value,
        )
        return StepResult(
            intent=action,
            decision=decision,
            outcome=StepOutcome.tool_error,
            tool_result=tool_result,
        )

    journal.record_proposal(
        action,
        decision,
        session_id=session_id,
        outcome=StepOutcome.executed.value,
    )
    return StepResult(
        intent=action,
        decision=decision,
        outcome=StepOutcome.executed,
        tool_result=tool_result,
    )


def execute_actions(
    actions: list[ActionIntent],
    gateway: ToolGateway,
    journal: AuditJournal,
    *,
    confirmations: ConfirmationStore | None = None,
    resolve_confirmation: ConfirmationResolver | None = None,
    session_id: str | None = None,
) -> PlanResult:
    """
    Classify and (when allowed) execute each ActionIntent in order.

    On confirm_required: create a digest-bound pending approval.
    If resolve_confirmation is provided, ask it for a phrase (or None to deny),
    then approve and execute or stop. If omitted, pause with pending set.
    """
    store = confirmations if confirmations is not None else ConfirmationStore()
    steps: list[StepResult] = []

    for action in actions:
        decision = classify(action)

        # Hard deny: journal and stop; never call a tool
        if decision.tier == PolicyTier.deny:
            journal.record_proposal(
                action,
                decision,
                session_id=session_id,
                outcome=StepOutcome.denied.value,
            )
            steps.append(
                StepResult(
                    intent=action,
                    decision=decision,
                    outcome=StepOutcome.denied,
                )
            )
            return PlanResult(
                steps=steps,
                completed=False,
                stop_reason=StepOutcome.denied,
            )

        # Confirm required: create pending, then resolve or pause
        if decision.tier == PolicyTier.confirm_required:
            journal.record_proposal(
                action,
                decision,
                session_id=session_id,
                outcome=StepOutcome.confirm_required.value,
            )
            pending = store.create(action, decision)

            # No resolver: pause so the caller can approve later via the store
            if resolve_confirmation is None:
                steps.append(
                    StepResult(
                        intent=action,
                        decision=decision,
                        outcome=StepOutcome.confirm_required,
                    )
                )
                return PlanResult(
                    steps=steps,
                    completed=False,
                    stop_reason=StepOutcome.confirm_required,
                    pending=pending,
                )

            phrase = resolve_confirmation(pending)
            if phrase is None:
                store.deny(pending.intent_digest)
                journal.record_proposal(
                    action,
                    decision,
                    session_id=session_id,
                    outcome=StepOutcome.confirmation_denied.value,
                )
                steps.append(
                    StepResult(
                        intent=action,
                        decision=decision,
                        outcome=StepOutcome.confirmation_denied,
                    )
                )
                return PlanResult(
                    steps=steps,
                    completed=False,
                    stop_reason=StepOutcome.confirmation_denied,
                    pending=pending,
                )

            confirmation = store.approve(pending.intent_digest, phrase)
            if confirmation.status != ConfirmationStatus.granted:
                journal.record_proposal(
                    action,
                    decision,
                    session_id=session_id,
                    outcome=StepOutcome.confirmation_denied.value,
                )
                steps.append(
                    StepResult(
                        intent=action,
                        decision=decision,
                        outcome=StepOutcome.confirmation_denied,
                    )
                )
                return PlanResult(
                    steps=steps,
                    completed=False,
                    stop_reason=StepOutcome.confirmation_denied,
                    pending=pending,
                )

            journal.record_proposal(
                action,
                decision,
                session_id=session_id,
                outcome=StepOutcome.confirmation_granted.value,
            )
            # Fall through to the same dispatch path as auto_pass
            step = _dispatch_tool(
                action,
                decision,
                gateway,
                journal,
                session_id=session_id,
            )
            steps.append(step)
            if step.outcome == StepOutcome.tool_error:
                return PlanResult(
                    steps=steps,
                    completed=False,
                    stop_reason=StepOutcome.tool_error,
                )
            continue

        # auto_pass: dispatch through ToolGateway
        step = _dispatch_tool(
            action,
            decision,
            gateway,
            journal,
            session_id=session_id,
        )
        steps.append(step)
        if step.outcome == StepOutcome.tool_error:
            return PlanResult(
                steps=steps,
                completed=False,
                stop_reason=StepOutcome.tool_error,
            )

    return PlanResult(steps=steps, completed=True, stop_reason=None)
