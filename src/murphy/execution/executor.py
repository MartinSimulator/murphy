# executor.py runs an ordered list of ActionIntents one at a time.
# Day 4: auto_pass calls ToolGateway; deny and confirm_required stop the plan.
# Todo: add confirmation tokens

from __future__ import annotations

from enum import Enum

from pydantic import BaseModel, ConfigDict

from murphy.audit.journal import AuditJournal
from murphy.mcp.tool_gateway import ToolGateway, ToolResult
from murphy.policy.gateway import PolicyDecision, PolicyTier, classify
from murphy.policy.intent import ActionIntent


# Why a single step finished (or why the plan stopped on it)
class StepOutcome(str, Enum):
    executed = "executed"
    denied = "denied"
    confirm_required = "confirm_required"
    tool_error = "tool_error"

# One step's policy decision plus optional tool call result
class StepResult(BaseModel):
    model_config = ConfigDict(frozen=True)
    intent: ActionIntent
    decision: PolicyDecision
    outcome: StepOutcome
    tool_result: ToolResult | None = None

# Result of running a whole plan; stopped=True means later actions were not attempted
class PlanResult(BaseModel):
    model_config = ConfigDict(frozen=True)
    steps: list[StepResult]
    completed: bool
    stop_reason: StepOutcome | None = None


# Execute a list of ActionIntents one at a time
def execute_actions(
    actions: list[ActionIntent],
    gateway: ToolGateway,
    journal: AuditJournal,
    *,
    session_id: str | None = None,
) -> PlanResult:
    """
    Classify and (when allowed) execute each ActionIntent in order.

    Stops on deny, confirm_required, or a failed tool call.
    """
    steps: list[StepResult] = []

    for action in actions:
        decision = classify(action)

        # if the decision is deny, record the proposal and return the plan result
        if decision.tier == PolicyTier.deny:
            journal.record_proposal(
                action,
                decision,
                session_id=session_id,
                outcome=StepOutcome.denied.value,
            )
            step = StepResult(
                intent=action,
                decision=decision,
                outcome=StepOutcome.denied,
            )
            steps.append(step)
            return PlanResult(
                steps=steps,
                completed=False,
                stop_reason=StepOutcome.denied,
            )

        # if the decision is confirm_required, record the proposal and return the plan result
        if decision.tier == PolicyTier.confirm_required:
            # Day 5 will pause for a digest-bound confirmation instead of stopping cold
            journal.record_proposal(
                action,
                decision,
                session_id=session_id,
                outcome=StepOutcome.confirm_required.value,
            )
            step = StepResult(
                intent=action,
                decision=decision,
                outcome=StepOutcome.confirm_required,
            )
            steps.append(step)
            return PlanResult(
                steps=steps,
                completed=False,
                stop_reason=StepOutcome.confirm_required,
            )

        # decision is neither deny nor confirm_required, so we call the tool
        tool_result = gateway.call(action)
        # if the tool call failed, record the proposal and return the plan result
        if not tool_result.ok:
            journal.record_proposal(
                action,
                decision,
                session_id=session_id,
                outcome=StepOutcome.tool_error.value,
            )
            step = StepResult(
                intent=action,
                decision=decision,
                outcome=StepOutcome.tool_error,
                tool_result=tool_result,
            )
            steps.append(step)
            return PlanResult(
                steps=steps,
                completed=False,
                stop_reason=StepOutcome.tool_error,
            )

        # if the tool call succeeded, record the proposal and add the step to the plan result
        journal.record_proposal(
            action,
            decision,
            session_id=session_id,
            outcome=StepOutcome.executed.value,
        )
        steps.append(
            StepResult(
                intent=action,
                decision=decision,
                outcome=StepOutcome.executed,
                tool_result=tool_result,
            )
        )

    # if we made it through all the actions, return the plan result
    return PlanResult(steps=steps, completed=True, stop_reason=None)
