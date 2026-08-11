# Planning: DeepSeek (or FakeLLM) is building ActionIntents from user text.

from __future__ import annotations

from murphy.app.state import AppState


class PlanningHandler:
    @property
    def state(self) -> AppState:
        return AppState.PLANNING

    def allowed_transitions(self) -> frozenset[AppState]:
        # executing: auto-pass plan started; awaiting_confirmation: first step
        # needs approval; idle: narration-only / plan failed cleanly
        return frozenset(
            {
                AppState.EXECUTING,
                AppState.AWAITING_CONFIRMATION,
                AppState.IDLE,
                AppState.DEGRADED,
            }
        )

    def on_enter(self) -> None:
        return None

    def on_exit(self) -> None:
        return None
