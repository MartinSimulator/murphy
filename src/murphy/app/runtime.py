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
from murphy.voice.capture import AudioCapture, AudioCaptureProtocol, CaptureResult
from murphy.voice.stt import Transcriber, default_transcriber

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
        capture: AudioCaptureProtocol | None = None,
        transcriber: Transcriber | None = None,
    ) -> None:
        self._llm = llm 
        self._owns_gateway = gateway is None # bool to indicate if we own the gateway
        self._gateway = gateway if gateway is not None else _build_fake_gateway()
        self._owns_journal = journal is None # bool to indicate if we own the journal
        self._journal = journal if journal is not None else AuditJournal()
        self._confirmations = (
            confirmations if confirmations is not None else ConfirmationStore()
        )
        self._machine = (
            state_machine if state_machine is not None else AppStateMachine()
        )
        # Real mic by default; tests inject FakeAudioCapture
        self._capture: AudioCaptureProtocol = (
            capture if capture is not None else AudioCapture()
        )
        # Production default is MLX Whisper; tests inject StubTranscriber
        self._transcriber: Transcriber = (
            transcriber if transcriber is not None else default_transcriber()
        )
        self._stt_ready = False

        self._listening_armed = False
        self._status_message = "Ready."
        self._worker: threading.Thread | None = None
        self._ptt_thread: threading.Thread | None = None
        self._confirm_event = threading.Event()
        self._confirm_phrase: str | None = None
        self._pending: PendingConfirmation | None = None
        self._ptt_from_confirmation = False
        self._last_heard: str | None = None
        self._lock = threading.Lock()

    def start(self) -> None:
        """Arm listening and warm the STT model so the first PTT is fast."""
        with self._lock:
            self._listening_armed = True
            if self._machine.get_state() is AppState.DEGRADED:
                self._status_message = "Listening armed, but still degraded."
                return
            self._status_message = "Warming speech-to-text…"

        warm = getattr(self._transcriber, "warmup", None)
        if not callable(warm):
            with self._lock:
                self._stt_ready = True
                self._status_message = "Listening armed. Use Push to Talk to speak."
            return

        def _warm_worker() -> None:
            try:
                warm()
                with self._lock:
                    self._stt_ready = True
                    if self._machine.get_state() is AppState.DEGRADED:
                        self._status_message = (
                            "Listening armed, but still degraded."
                        )
                    else:
                        self._status_message = (
                            "Listening armed. STT ready. Use Push to Talk."
                        )
            except Exception as exc:  # noqa: BLE001
                with self._lock:
                    self._stt_ready = False
                    if self._machine.get_state() is not AppState.DEGRADED:
                        self._machine.transition_to(AppState.DEGRADED)
                    self._status_message = f"STT failed to load: {exc}"

        threading.Thread(
            target=_warm_worker,
            name="murphy-stt-warm",
            daemon=True,
        ).start()

    def stop(self) -> None:
        """Disarm listening; cancel PTT and deny any confirmation wait."""
        with self._lock:
            self._listening_armed = False
            self._status_message = "Stopped."
        if self.get_state() is AppState.LISTENING:
            self.end_ptt()
        self.deny_confirmation()

    def close(self) -> None:
        """Release resources owned by this controller."""
        if self.get_state() is AppState.LISTENING:
            try:
                self._capture.stop()
            except Exception:
                pass
        self.stop()
        if self._ptt_thread is not None and self._ptt_thread.is_alive():
            self._ptt_thread.join(timeout=5.0)
        if self._worker is not None and self._worker.is_alive():
            self._worker.join(timeout=_CONFIRM_WAIT_SECONDS + 5.0)
        close_llm = getattr(self._llm, "close", None)
        if callable(close_llm):
            close_llm()
        if self._owns_journal:
            self._journal.close()

    def get_state(self) -> AppState:
        return self._machine.get_state()

    @property
    def journal(self) -> AuditJournal:
        """Audit journal used by the menu log viewer."""
        return self._journal

    def status_message(self) -> str:
        with self._lock:
            return self._status_message

    def is_listening_armed(self) -> bool:
        with self._lock:
            return self._listening_armed

    def is_ptt_active(self) -> bool:
        return self._machine.get_state() is AppState.LISTENING

    def pending_confirmation(self) -> PendingConfirmation | None:
        with self._lock:
            return self._pending

    def set_project_root(self, project_root: Path) -> None:
        save_project_root(project_root)
        with self._lock:
            self._status_message = f"Project root set to {project_root}."

    def clear_degraded(self) -> None:
        """Return from degraded to idle and retry STT warmup if needed."""
        with self._lock:
            if self._machine.get_state() is not AppState.DEGRADED:
                return
            self._machine.transition_to(AppState.IDLE)
            self._status_message = "Ready."
        # Retry model load after a previous STT failure
        if not self._stt_ready and callable(getattr(self._transcriber, "warmup", None)):
            self.start()

    def begin_ptt(self) -> None:
        """
        Start push-to-talk capture.

        Allowed from idle (new ask) or awaiting_confirmation (spoken phrase).
        """
        with self._lock:
            state = self._machine.get_state()
            if state not in (AppState.IDLE, AppState.AWAITING_CONFIRMATION):
                self._status_message = (
                    f"Cannot start push-to-talk from {state.value}."
                )
                return
            if not self._listening_armed and state is AppState.IDLE:
                # Allow PTT without a separate Start Listening click for v1 UX
                self._listening_armed = True
            self._ptt_from_confirmation = state is AppState.AWAITING_CONFIRMATION
            self._machine.transition_to(AppState.LISTENING)
            self._status_message = "Listening… speak, then choose Push to Talk Stop."

        try:
            self._capture.start()
        except Exception as exc:  # noqa: BLE001
            with self._lock:
                target = (
                    AppState.AWAITING_CONFIRMATION
                    if self._ptt_from_confirmation
                    else AppState.IDLE
                )
                if self._machine.get_state() is AppState.LISTENING:
                    self._machine.transition_to(target)
                self._status_message = f"Microphone error: {exc}"

    def end_ptt(self) -> None:
        """Stop capture, transcribe on a worker, then submit text or a confirm phrase."""
        with self._lock:
            if self._machine.get_state() is not AppState.LISTENING:
                self._status_message = "Push-to-talk is not active."
                return
            if self._ptt_thread is not None and self._ptt_thread.is_alive():
                self._status_message = "Still finishing the previous take."
                return
            from_confirm = self._ptt_from_confirmation
            self._machine.transition_to(AppState.TRANSCRIBING)
            self._status_message = "Transcribing…"
            thread = threading.Thread(
                target=self._finish_ptt,
                args=(from_confirm,),
                name="murphy-ptt-finish",
                daemon=True,
            )
            self._ptt_thread = thread
        thread.start()

    def submit_text(self, text: str) -> None:
        """
        Accept typed (or STT) text and run handle_text on a worker thread.

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
                target=self._run_handle_text, # tell the worker to call handle_text
                args=(cleaned, project_root), # pass the cleaned text and project root
                name="murphy-handle-text", # name the thread
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

    def _finish_ptt(self, from_confirmation: bool) -> None:
        try:
            result = self._capture.stop()
        except Exception as exc:  # noqa: BLE001
            with self._lock:
                if self._machine.get_state() is AppState.TRANSCRIBING:
                    self._machine.transition_to(AppState.DEGRADED)
                self._status_message = f"Capture failed: {exc}"
            return

        text = ""
        if not result.is_empty:
            try:
                text = self._transcriber.transcribe(
                    result.samples, result.sample_rate
                ).strip()
            except Exception as exc:  # noqa: BLE001
                with self._lock:
                    if self._machine.get_state() is AppState.TRANSCRIBING:
                        self._machine.transition_to(AppState.DEGRADED)
                    self._status_message = f"Transcription failed: {exc}"
                return

        if not text:
            self._handle_empty_ptt(from_confirmation, result)
            return

        if from_confirmation:
            with self._lock:
                if self._machine.get_state() is AppState.TRANSCRIBING:
                    self._machine.transition_to(AppState.AWAITING_CONFIRMATION)
                self._last_heard = text
            self.submit_confirmation_phrase(text)
            return

        with self._lock:
            if self._machine.get_state() is AppState.TRANSCRIBING:
                self._machine.transition_to(AppState.IDLE)
            self._last_heard = text
            self._status_message = f"Heard: {text}"
        self.submit_text(text)

    def _handle_empty_ptt(
        self, from_confirmation: bool, result: CaptureResult
    ) -> None:
        with self._lock:
            if self._machine.get_state() is not AppState.TRANSCRIBING:
                return
            if from_confirmation:
                self._machine.transition_to(AppState.AWAITING_CONFIRMATION)
                self._status_message = (
                    "No speech detected; confirmation still pending."
                )
            else:
                self._machine.transition_to(AppState.IDLE)
                if result.is_empty:
                    self._status_message = "No audio captured."
                else:
                    self._status_message = (
                        "No speech detected (STT not configured yet, or silence)."
                    )

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

            message = result.message
            if result.error and result.assistant_text:
                message = f"{result.message} {result.assistant_text}"
            if self._last_heard and result.error:
                message = f"Heard: {self._last_heard} · {message}"
            self._status_message = message
            self._pending = None
