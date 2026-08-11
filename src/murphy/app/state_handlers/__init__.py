# state_handlers: one StateHandler per AppState with the legal next states.

from __future__ import annotations

from murphy.app.state import AppState, StateHandler
from murphy.app.state_handlers.awaiting_confirmation import AwaitingConfirmationHandler
from murphy.app.state_handlers.degraded import DegradedHandler
from murphy.app.state_handlers.executing import ExecutingHandler
from murphy.app.state_handlers.idle import IdleHandler
from murphy.app.state_handlers.listening import ListeningHandler
from murphy.app.state_handlers.planning import PlanningHandler
from murphy.app.state_handlers.transcribing import TranscribingHandler

# Build a map of AppStates to StateHandlers
def default_handlers() -> dict[AppState, StateHandler]:
    """Build a fresh handler map for one AppStateMachine."""
    handlers: list[StateHandler] = [
        IdleHandler(),
        ListeningHandler(),
        TranscribingHandler(),
        PlanningHandler(),
        AwaitingConfirmationHandler(),
        ExecutingHandler(),
        DegradedHandler(),
    ]
    return {handler.state: handler for handler in handlers}
