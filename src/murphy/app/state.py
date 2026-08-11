# state.py defines AppState and the runtime state machine.
# Handlers in state_handlers/ declare legal transitions; AppStateMachine enforces them.
# UI and voice must not call tools or the LLM; they only ask the runtime to transition.

from __future__ import annotations

from enum import Enum
from typing import Protocol


# AppState is an enum of the possible states Murphy can be in
class AppState(Enum):
    IDLE = "idle"
    LISTENING = "listening"
    TRANSCRIBING = "transcribing"
    PLANNING = "planning"
    AWAITING_CONFIRMATION = "awaiting_confirmation"
    EXECUTING = "executing"
    DEGRADED = "degraded"  # Murphy is running but something is broken


class IllegalTransitionError(ValueError):
    """Raised when a requested AppState transition is not allowed."""


# Per-state behavior: identity, allowed next states, and optional enter/exit hooks.
class StateHandler(Protocol):
    @property
    def state(self) -> AppState:
        ...

    def allowed_transitions(self) -> frozenset[AppState]:
        ...

    def on_enter(self) -> None:
        ...

    def on_exit(self) -> None:
        ...


# AppStateMachine is the runtime state machine. It validates and applies AppState transitions using registered StateHandlers.
class AppStateMachine:
    """Validate and apply AppState transitions using registered StateHandlers."""

    def __init__(
        self,
        *,
        initial: AppState = AppState.IDLE,
        handlers: dict[AppState, StateHandler] | None = None,
    ) -> None:
        # Import here to avoid a circular import with state_handlers.
        if handlers is None:
            from murphy.app.state_handlers import default_handlers

            handlers = default_handlers()
        self._handlers = handlers
        if initial not in self._handlers:
            raise ValueError(f"No handler registered for initial state {initial!r}")
        self._state = initial
        self._handlers[initial].on_enter()

    def get_state(self) -> AppState:
        return self._state

    def transition_to(self, state: AppState) -> None:
        if state == self._state:
            return

        current = self._handlers[self._state]
        if state not in current.allowed_transitions():
            raise IllegalTransitionError(
                f"Cannot transition from {self._state.value} to {state.value}"
            )
        if state not in self._handlers:
            raise ValueError(f"No handler registered for state {state!r}")

        current.on_exit()
        self._state = state
        self._handlers[state].on_enter()
