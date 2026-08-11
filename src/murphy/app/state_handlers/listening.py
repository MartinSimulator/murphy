# Listening: microphone is open (push-to-talk or, later, post-wake capture).

from __future__ import annotations

from murphy.app.state import AppState


class ListeningHandler:
    @property
    def state(self) -> AppState:
        return AppState.LISTENING

    def allowed_transitions(self) -> frozenset[AppState]:
        # transcribing: user released PTT; idle: cancel; awaiting_confirmation:
        # cancel PTT while confirming; degraded: capture failure
        return frozenset(
            {
                AppState.TRANSCRIBING,
                AppState.IDLE,
                AppState.AWAITING_CONFIRMATION,
                AppState.DEGRADED,
            }
        )

    def on_enter(self) -> None:
        return None

    def on_exit(self) -> None:
        return None
