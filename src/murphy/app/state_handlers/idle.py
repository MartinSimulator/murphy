# Idle: ready for typed ask or push-to-talk; not mid-request.

from __future__ import annotations

from murphy.app.state import AppState


class IdleHandler:
    @property
    def state(self) -> AppState:
        return AppState.IDLE

    def allowed_transitions(self) -> frozenset[AppState]:
        # listening: start PTT; planning: typed ask; degraded: critical failure
        return frozenset(
            {
                AppState.LISTENING,
                AppState.PLANNING,
                AppState.DEGRADED,
            }
        )

    def on_enter(self) -> None:
        return None

    def on_exit(self) -> None:
        return None
