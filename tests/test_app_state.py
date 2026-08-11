"""Tests for AppStateMachine transitions and state handlers."""

from __future__ import annotations

import pytest

from murphy.app.state import AppStateMachine
from murphy.app.state import AppState, IllegalTransitionError
from murphy.app.state_handlers import default_handlers


def test_default_handlers_cover_every_app_state() -> None:
    handlers = default_handlers()
    assert set(handlers) == set(AppState)
    for state, handler in handlers.items():
        assert handler.state is state


def test_starts_idle() -> None:
    machine = AppStateMachine()
    assert machine.get_state() is AppState.IDLE


def test_typed_ask_happy_path() -> None:
    machine = AppStateMachine()
    machine.transition_to(AppState.PLANNING)
    machine.transition_to(AppState.EXECUTING)
    machine.transition_to(AppState.IDLE)
    assert machine.get_state() is AppState.IDLE


def test_voice_ask_with_confirmation() -> None:
    machine = AppStateMachine()
    machine.transition_to(AppState.LISTENING)
    machine.transition_to(AppState.TRANSCRIBING)
    machine.transition_to(AppState.PLANNING)
    machine.transition_to(AppState.AWAITING_CONFIRMATION)
    machine.transition_to(AppState.LISTENING)
    machine.transition_to(AppState.TRANSCRIBING)
    machine.transition_to(AppState.EXECUTING)
    machine.transition_to(AppState.IDLE)
    assert machine.get_state() is AppState.IDLE


def test_degraded_only_recovers_to_idle() -> None:
    machine = AppStateMachine()
    machine.transition_to(AppState.DEGRADED)
    with pytest.raises(IllegalTransitionError):
        machine.transition_to(AppState.PLANNING)
    machine.transition_to(AppState.IDLE)
    assert machine.get_state() is AppState.IDLE


def test_illegal_transition_raises() -> None:
    machine = AppStateMachine()
    with pytest.raises(IllegalTransitionError, match="idle.*executing"):
        machine.transition_to(AppState.EXECUTING)


def test_same_state_transition_is_noop() -> None:
    machine = AppStateMachine()
    machine.transition_to(AppState.IDLE)
    assert machine.get_state() is AppState.IDLE


def test_enter_exit_hooks_run_in_order() -> None:
    events: list[str] = []

    class RecordingHandler:
        def __init__(self, state: AppState, allowed: frozenset[AppState]) -> None:
            self._state = state
            self._allowed = allowed

        @property
        def state(self) -> AppState:
            return self._state

        def allowed_transitions(self) -> frozenset[AppState]:
            return self._allowed

        def on_enter(self) -> None:
            events.append(f"enter:{self._state.value}")

        def on_exit(self) -> None:
            events.append(f"exit:{self._state.value}")

    handlers = {
        AppState.IDLE: RecordingHandler(
            AppState.IDLE, frozenset({AppState.PLANNING})
        ),
        AppState.PLANNING: RecordingHandler(
            AppState.PLANNING, frozenset({AppState.IDLE})
        ),
    }
    machine = AppStateMachine(initial=AppState.IDLE, handlers=handlers)
    machine.transition_to(AppState.PLANNING)

    assert events == ["enter:idle", "exit:idle", "enter:planning"]
