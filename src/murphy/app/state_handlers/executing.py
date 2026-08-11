# Executing: authorized ActionIntent(s) are running through ToolGateway.

from __future__ import annotations

from murphy.app.state import AppState


class ExecutingHandler:
    @property
    def state(self) -> AppState:
        return AppState.EXECUTING

    def allowed_transitions(self) -> frozenset[AppState]:
        # awaiting_confirmation: a later step needs approval; idle: plan done
        # or stopped
        return frozenset(
            {
                AppState.AWAITING_CONFIRMATION,
                AppState.IDLE,
                AppState.DEGRADED,
            }
        )

    def on_enter(self) -> None:
        return None

    def on_exit(self) -> None:
        return None
