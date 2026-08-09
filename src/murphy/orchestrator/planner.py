# planner.py turns user text into validated ActionIntents via an LLMClient.
# It does not call ToolGateway, classify policy, or collect confirmation.

from __future__ import annotations

from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field

from murphy.orchestrator.config import get_llm_config
from murphy.orchestrator.llm import (
    LLMClient,
    LLMRequest,
    LLMResponse,
    LLMResponseError,
    LLMUnavailableError,
    ToolProposal,
)
from murphy.orchestrator.tools_for_prompt import tools_for_prompt
from murphy.policy.intent import ActionIntent, build_validated_action_intent
from murphy.policy.schema import SchemaValidationError
from murphy.policy.side_effects import side_effect_for


class PlanBuildError(Exception):
    """Raised when the model proposals cannot be turned into valid ActionIntents."""


class PlannerResult(BaseModel):
    model_config = ConfigDict(frozen=True)

    intents: list[ActionIntent] = Field(default_factory=list)
    assistant_text: str | None = None


_SYSTEM_PROMPT = """
You are Murphy, a local developer orchestration assistant running on the user's machine.

You do not write or edit source code.
Only use the tools provided in this request; do not invent tools or arguments.
project_root is fixed by the caller; do not invent filesystem roots outside it.

When the request maps to one or more available tools, propose an ordered list of
tool calls that accomplishes it, including destructive or irreversible actions
(e.g. force push, pruning, deleting). A separate system evaluates every proposed
call and requires explicit user confirmation before anything executes. Do not
refuse, hedge, or add your own safety caveats for actions the tools support.
Propose exactly what was asked and let that system decide.

If the request is ambiguous in a way that matters (e.g. no target branch, no
scope specified for a broad operation), ask a brief clarifying question instead
of guessing.

If the request cannot be done with the listed tools, say so briefly and make no
tool calls.

If the user is not issuing a command (asking a question, discussing the
project, or talking through a design decision) respond conversationally with
no tool calls. This is normal, not a fallback.

Responses may be read aloud. Keep them concise, plain sentences (markdown,
lists, or code blocks are not allowed).
"""

# convert the model tool proposals into schema-validated ActionIntents
def _proposals_to_intents(
    proposals: list[ToolProposal],
    *,
    project_root: Path,
) -> list[ActionIntent]:
    """Convert model tool proposals into schema-validated ActionIntents."""
    intents: list[ActionIntent] = []
    for proposal in proposals:
        side_effect = side_effect_for(proposal.server, proposal.tool)
        intent = build_validated_action_intent(
            server=proposal.server,
            tool=proposal.tool,
            args=proposal.args,
            project_root=project_root,
            side_effect=side_effect,
        )
        intents.append(intent)
    return intents

# plan the user's text into a list of ActionIntents
def plan(
    user_text: str,
    *,
    project_root: Path,
    llm: LLMClient,
    max_tool_rounds: int | None = None,
    servers: set[str] | None = None,
) -> PlannerResult:
    """
    Ask the LLM for tool calls, validate them, and return ActionIntents.

    Propagates LLMUnavailableError / LLMResponseError from the client.
    Raises PlanBuildError when proposals fail schema validation after retries.
    """
    rounds = max_tool_rounds if max_tool_rounds is not None else get_llm_config().max_tool_rounds # make sure we haven't exceeded the max number of tool rounds
    tools = tools_for_prompt(servers=servers)
    messages: list[dict] = []
    last_error: str | None = None

    for attempt in range(rounds): # loop through the number of tool rounds
        if attempt > 0 and last_error is not None: # if we have an error from the previous round, add it to the messages
            messages = [
                *messages,
                {
                    "role": "user",
                    "content": (
                        "Your previous tool calls were invalid. "
                        f"Fix them. Error: {last_error}"
                    ),
                },
            ]
        # create the LLM request
        request = LLMRequest(
            system=_SYSTEM_PROMPT,
            user=user_text,
            tools=tools,
            messages=messages,
        )
        response: LLMResponse = llm.complete(request) # get the response from the LLM

        # if there are no tool calls, return the response text
        if not response.tool_calls:
            return PlannerResult(intents=[], assistant_text=response.text)

        try:
            # convert the tool calls into schema-validated ActionIntents
            intents = _proposals_to_intents(
                list(response.tool_calls),
                project_root=project_root,
            )
        except (SchemaValidationError, KeyError, ValueError) as exc:
            last_error = str(exc)
            if attempt + 1 >= rounds:
                raise PlanBuildError(
                    f"Failed to build intents after {rounds} round(s): {last_error}"
                ) from exc
            continue

        return PlannerResult(intents=intents, assistant_text=response.text)

    raise PlanBuildError("Failed to plan: no successful round")


# Re-export client errors so callers can catch planning transport failures from one place
__all__ = [
    "PlanBuildError",
    "PlannerResult",
    "plan",
    "LLMUnavailableError",
    "LLMResponseError",
]
