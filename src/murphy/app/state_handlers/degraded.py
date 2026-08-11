# Degraded: shell is up but a critical component failed (e.g. LLM unreachable).
# Unrelated MCP downtime is per-server status, not this global state.

from __future__ import annotations

from murphy.app.state import AppState


class DegradedHandler:
    @property
    def state(self) -> AppState:
        return AppState.DEGRADED

    def allowed_transitions(self) -> frozenset[AppState]:
        # idle: operator recovered or dismissed the failure
        return frozenset({AppState.IDLE})

    def on_enter(self) -> None:
        return None

    def on_exit(self) -> None:
        return None
