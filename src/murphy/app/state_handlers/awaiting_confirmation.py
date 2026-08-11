# Awaiting confirmation: digest-bound phrase required before ToolGateway.call.

from __future__ import annotations

from murphy.app.state import AppState


class AwaitingConfirmationHandler:
    @property
    def state(self) -> AppState:
        return AppState.AWAITING_CONFIRMATION

    def allowed_transitions(self) -> frozenset[AppState]:
        # listening: PTT for spoken phrase; executing: phrase granted;
        # idle: deny / expire
        return frozenset(
            {
                AppState.LISTENING,
                AppState.EXECUTING,
                AppState.IDLE,
                AppState.DEGRADED,
            }
        )

    def on_enter(self) -> None:
        return None

    def on_exit(self) -> None:
        return None
