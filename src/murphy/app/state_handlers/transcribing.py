# Transcribing: local STT is turning captured audio into text.

from __future__ import annotations

from murphy.app.state import AppState


class TranscribingHandler:
    @property
    def state(self) -> AppState:
        return AppState.TRANSCRIBING

    def allowed_transitions(self) -> frozenset[AppState]:
        # planning: new ask text; awaiting_confirmation: confirm phrase mismatch
        # still open; executing: confirm phrase granted; idle: empty/cancel
        return frozenset(
            {
                AppState.PLANNING,
                AppState.AWAITING_CONFIRMATION,
                AppState.EXECUTING,
                AppState.IDLE,
                AppState.DEGRADED,
            }
        )

    def on_enter(self) -> None:
        return None

    def on_exit(self) -> None:
        return None
