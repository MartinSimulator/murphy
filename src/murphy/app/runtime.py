# runtime.py is the long-lived coordinator between UI/voice and handle_text.
# Menu callbacks must only call methods here; LLM and tools run on a worker thread.

from __future__ import annotations

import threading
from pathlib import Path

from murphy.app.settings import load_project_root, save_project_root
from murphy.app.state import AppState, AppStateMachine
from murphy.audit.journal import AuditJournal
from murphy.execution.confirmation import ConfirmationStore, PendingConfirmation
from murphy.mcp.fake_handlers.docker import docker_handler
from murphy.mcp.fake_handlers.git import git_handler
from murphy.mcp.tool_gateway import ToolGateway
from murphy.orchestrator.llm import LLMClient
from murphy.orchestrator.router import HandleResult, handle_text

# Match ConfirmationStore's default TTL so a silent UI does not hang forever
_CONFIRM_WAIT_SECONDS = 60.0


def _build_fake_gateway() -> ToolGateway:
    """Same in-process git/docker fakes used by murphy ask."""
    gateway = ToolGateway()
    gateway.register_handler("git", git_handler)
    gateway.register_handler("docker", docker_handler)
    gateway.start()
    return gateway


class RuntimeController:
    """Own shared resources, drive AppState, and run handle_text off the UI thread."""

    def __init__(
        self,
        *,
        llm: LLMClient,
        gateway: ToolGateway | None = None,
        journal: AuditJournal | None = None,
        confirmations: ConfirmationStore | None = None,
        state_machine: AppStateMachine | None = None,
    ) -> None:
        self._llm = llm
        self._owns_gateway = gateway is None
        self._gateway = gateway if gateway is not None else _build_fake_gateway()
        self._owns_journal = journal is None
        self._journal = journal if journal is not None else AuditJournal()
        self._confirmations = (
            confirmations if confirmations is not None else ConfirmationStore()
        )
        self._machine = (
            state_machine if state_machine is not None else AppStateMachine()
        )

        # Listening readiness (PTT armed); wake-word comes later
        self._listening_armed = False
        # Human-readable status for the menu (especially when degraded)
        self._status_message = "Ready."
        # Worker that runs handle_text; None when idle
        self._worker: threading.Thread | None = None
        # Confirmation hand-off between worker (resolver) and UI thread
        self._confirm_event = threading.Event()
        self._confirm_phrase: str | None = None
        self._pending: PendingConfirmation | None = None
        # Serialize state / status / confirm fields across threads
        self._lock = threading.Lock()

    def start(self) -> None:
        """Arm listening so push-to-talk may begin (wake-word later)."""
        with self._lock:
            self._listening_armed = True
            if self._machine.get_state() is AppState.DEGRADED:
                self._status_message = "Listening armed, but still degraded."
            else:
                self._status_message = "Listening armed."

    def stop(self) -> None:
        """Disarm listening and deny any confirmation wait in progress."""
        with self._lock:
            self._listening_armed = False
            self._status_message = "Stopped."
        self.deny_confirmation()

    def close(self) -> None:
        """Release resources owned by this controller."""
        self.stop()
        if self._worker is not None and self._worker.is_alive():
            self._worker.join(timeout=_CONFIRM_WAIT_SECONDS + 5.0)
        close_llm = getattr(self._llm, "close", None)
        if callable(close_llm):
            close_llm()
        if self._owns_journal:
            self._journal.close()

    def get_state(self) -> AppState:
        return self._machine.get_state()

    def status_message(self) -> str:
        with self._lock:
            return self._status_message

    def is_listening_armed(self) -> bool:
        with self._lock:
            return self._listening_armed

    def pending_confirmation(self) -> PendingConfirmation | None:
        with self._lock:
            return self._pending

    def set_project_root(self, project_root: Path) -> None:
        save_project_root(project_root)
        with self._lock:
            self._status_message = f"Project root set to {project_root}."

    def clear_degraded(self) -> None:
        """Return from degraded to idle after the operator recovers."""
        with self._lock:
            if self._machine.get_state() is AppState.DEGRADED:
                self._machine.transition_to(AppState.IDLE)
                self._status_message = "Ready."

    def submit_text(self, text: str) -> None:
        """
        Accept typed (or later STT) text and run handle_text on a worker thread.

        Returns immediately. Rejects if a request is already in flight or project
        root is unset.
        """
        cleaned = text.strip()
        if not cleaned:
            with self._lock:
                self._status_message = "Empty request ignored."
            return

        project_root = load_project_root()
        if project_root is None:
            with self._lock:
                self._status_message = (
                    "Set a project root before asking Murphy to run tools."
                )
            return

        with self._lock:
            if self._worker is not None and self._worker.is_alive():
                self._status_message = "Busy; finish or deny the current request."
                return
            state = self._machine.get_state()
            if state is AppState.DEGRADED:
                self._status_message = (
                    "Degraded; clear the failure before submitting again."
                )
                return
            if state is not AppState.IDLE:
                self._status_message = f"Busy ({state.value}); try again when idle."
                return
            self._machine.transition_to(AppState.PLANNING)
            self._status_message = "Planning…"
            self._confirm_event.clear()
            self._confirm_phrase = None
            self._pending = None
            # Assign under the lock so a second submit_text cannot race in
            worker = threading.Thread(
                target=self._run_handle_text,
                args=(cleaned, project_root),
                name="murphy-handle-text",
                daemon=True,
            )
            self._worker = worker
        worker.start()

    def submit_confirmation_phrase(self, phrase: str) -> None:
        """Unblock a waiting ConfirmationResolver with an approval phrase."""
        with self._lock:
            if self._machine.get_state() is not AppState.AWAITING_CONFIRMATION:
                self._status_message = "No confirmation is pending."
                return
            self._confirm_phrase = phrase
            self._confirm_event.set()

    def deny_confirmation(self) -> None:
        """Unblock a waiting ConfirmationResolver with a denial (None phrase)."""
        with self._lock:
            self._confirm_phrase = None
            self._confirm_event.set()
            if self._machine.get_state() is AppState.AWAITING_CONFIRMATION:
                self._status_message = "Confirmation denied."

    def _resolve_confirmation(self, pending: PendingConfirmation) -> str | None:
        """
        Blocking ConfirmationResolver used by execute_actions on the worker thread.

        Transitions into awaiting_confirmation, waits for the UI/voice, then
        returns a phrase or None. On a non-None phrase, moves to executing
        before the executor dispatches the tool.
        """
        with self._lock:
            state = self._machine.get_state()
            if state is AppState.PLANNING:
                self._machine.transition_to(AppState.AWAITING_CONFIRMATION)
            elif state is AppState.EXECUTING:
                self._machine.transition_to(AppState.AWAITING_CONFIRMATION)
            self._pending = pending
            self._confirm_phrase = None
            self._confirm_event.clear()
            self._status_message = (
                f"Confirmation required: say something like "
                f"'{pending.expected_phrase}'."
            )

        signaled = self._confirm_event.wait(timeout=_CONFIRM_WAIT_SECONDS)
        with self._lock:
            phrase = self._confirm_phrase if signaled else None
            self._pending = None
            if phrase is not None:
                self._machine.transition_to(AppState.EXECUTING)
                self._status_message = "Executing…"
            return phrase

    def _run_handle_text(self, text: str, project_root: Path) -> None:
        """Worker body: call handle_text, then land in idle or degraded."""
        try:
            result = handle_text(
                text,
                project_root=project_root,
                llm=self._llm,
                gateway=self._gateway,
                journal=self._journal,
                confirmations=self._confirmations,
                resolve_confirmation=self._resolve_confirmation,
                servers={"git", "docker"},
            )
        except Exception as exc:  # noqa: BLE001 - surface unexpected failures as degraded
            with self._lock:
                if self._machine.get_state() is not AppState.DEGRADED:
                    self._machine.transition_to(AppState.DEGRADED)
                self._status_message = f"Unexpected failure: {exc}"
            return
        finally:
            with self._lock:
                self._worker = None

        self._finish_from_result(result)

    def _finish_from_result(self, result: HandleResult) -> None:
        with self._lock:
            state = self._machine.get_state()
            if result.error == "llm_unavailable":
                if state is not AppState.DEGRADED:
                    self._machine.transition_to(AppState.DEGRADED)
                self._status_message = result.message
                return

            # Soft failures and success both return to idle for another ask
            if state is AppState.DEGRADED:
                self._status_message = result.message
                return
            if state is not AppState.IDLE:
                self._machine.transition_to(AppState.IDLE)
            self._status_message = result.message
            self._pending = None
