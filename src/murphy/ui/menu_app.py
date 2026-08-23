# menu_app.py is the PyObjC macOS menu bar shell.
# It only posts commands to RuntimeController; it never calls handle_text or tools.

from __future__ import annotations

import sys
from pathlib import Path

import objc
from AppKit import (
    NSAlert,
    NSAlertFirstButtonReturn,
    NSApp,
    NSApplication,
    NSApplicationActivationPolicyAccessory,
    NSMenu,
    NSMenuItem,
    NSModalResponseOK,
    NSOpenPanel,
    NSStatusBar,
    NSTextField,
    NSVariableStatusItemLength,
)
from Foundation import NSObject, NSTimer

from murphy.app.runtime import RuntimeController
from murphy.app.state import AppState
from murphy.app.settings import load_project_root
from murphy.orchestrator.deepseek import DeepSeekClient
from murphy.ui.log_viewer import LogViewerController

# How often the status title refreshes from RuntimeController
_STATUS_POLL_SECONDS = 0.5

# Helper function to get the state title
def _state_title(state: AppState) -> str:
    """Short label shown in the menu bar icon text."""
    labels = {
        AppState.IDLE: "Murphy",
        AppState.LISTENING: "Murphy · listen",
        AppState.TRANSCRIBING: "Murphy · stt",
        AppState.PLANNING: "Murphy · plan",
        AppState.AWAITING_CONFIRMATION: "Murphy · confirm?",
        AppState.EXECUTING: "Murphy · run",
        AppState.DEGRADED: "Murphy · degraded",
    }
    return labels.get(state, "Murphy")

# Helper function to prompt the user for text
def _prompt_text(title: str, message: str, default: str = "") -> str | None:
    """Modal NSAlert with a text field. Returns None if the user cancels."""
    # Accessory apps stay in the background unless we force activation;
    # otherwise alerts often open behind other windows (looks like "nothing happens").
    NSApp.activateIgnoringOtherApps_(True)

    alert = NSAlert.alloc().init()
    alert.setMessageText_(title)
    alert.setInformativeText_(message)
    alert.addButtonWithTitle_("OK")
    alert.addButtonWithTitle_("Cancel")

    field = NSTextField.alloc().initWithFrame_(((0, 0), (280, 24)))
    field.setStringValue_(default)
    alert.setAccessoryView_(field)
    alert.window().setInitialFirstResponder_(field)

    if alert.runModal() != NSAlertFirstButtonReturn:
        return None
    return field.stringValue().strip() or None


# Helper function to choose the project root directory
def _choose_directory() -> Path | None:
    """Native folder picker for project root."""
    NSApp.activateIgnoringOtherApps_(True)
    panel = NSOpenPanel.openPanel()
    panel.setCanChooseFiles_(False)
    panel.setCanChooseDirectories_(True)
    panel.setAllowsMultipleSelection_(False)
    panel.setMessage_("Choose the Murphy project root")
    if panel.runModal() != NSModalResponseOK:
        return None
    url = panel.URLs()[0]
    return Path(url.path())

# Class to own the status item and forward actions to RuntimeController
class MenuBarApp(NSObject):
    """
    AppKit delegate that owns the status item and forwards actions to RuntimeController.

    Objective-C action methods end with _ because the sender argument is required
    (selector form: doAsk:(id)sender → doAsk_).
    """

    runtime = objc.ivar()
    status_item = objc.ivar()
    status_menu = objc.ivar()
    log_viewer = objc.ivar()
    timer = objc.ivar()
    ask_item = objc.ivar()
    confirm_item = objc.ivar()
    deny_item = objc.ivar()
    start_item = objc.ivar()
    stop_item = objc.ivar()
    clear_degraded_item = objc.ivar()
    status_detail_item = objc.ivar()

    def initWithRuntime_(self, runtime: RuntimeController):
        self = objc.super(MenuBarApp, self).init()
        if self is None:
            return None
        self.runtime = runtime
        self.status_item = None
        self.status_menu = None
        self.log_viewer = None
        self.timer = None
        self.ask_item = None
        self.confirm_item = None
        self.deny_item = None
        self.start_item = None
        self.stop_item = None
        self.clear_degraded_item = None
        self.status_detail_item = None
        return self

    def applicationDidFinishLaunching_(self, notification) -> None:
        # Accessory policy: no Dock icon; menu bar only
        NSApp.setActivationPolicy_(NSApplicationActivationPolicyAccessory)
        self._build_status_item()
        self.log_viewer = LogViewerController.alloc().initWithJournal_(
            self.runtime.journal
        )
        # Warm STT/TTS off the UI thread (RuntimeController.start)
        self.runtime.start()
        # Poll status so the title tracks worker-thread state changes
        self.timer = NSTimer.scheduledTimerWithTimeInterval_target_selector_userInfo_repeats_(
            _STATUS_POLL_SECONDS,
            self,
            "refreshStatus:",
            None,
            True,
        )
        self.refreshStatus_(None)

    def applicationWillTerminate_(self, notification) -> None:
        if self.timer is not None:
            self.timer.invalidate()
            self.timer = None
        self.runtime.close()

    @objc.python_method
    def _build_status_item(self) -> None:
        bar = NSStatusBar.systemStatusBar()
        item = bar.statusItemWithLength_(NSVariableStatusItemLength)
        item.button().setTitle_("Murphy")

        menu = NSMenu.alloc().init()
        menu.setDelegate_(self)

        self.status_detail_item = NSMenuItem.alloc().initWithTitle_action_keyEquivalent_(
            "Status: Ready.", None, ""
        )
        self.status_detail_item.setEnabled_(False)
        menu.addItem_(self.status_detail_item)
        menu.addItem_(NSMenuItem.separatorItem())

        self.start_item = self._add(
            menu, "Push to Talk Start", "doStartPTT:", ""
        )
        self.stop_item = self._add(
            menu, "Push to Talk Stop", "doStopPTT:", ""
        )
        menu.addItem_(NSMenuItem.separatorItem())

        self.ask_item = self._add(menu, "Ask…", "doAsk:", "")
        self.confirm_item = self._add(menu, "Confirm…", "doConfirm:", "")
        self.deny_item = self._add(menu, "Deny Confirmation", "doDeny:", "")
        menu.addItem_(NSMenuItem.separatorItem())

        self._add(menu, "Set Project Root…", "doSetProjectRoot:", "")
        self._add(menu, "Show Log…", "doShowLog:", "")
        self.clear_degraded_item = self._add(
            menu, "Clear Degraded", "doClearDegraded:", ""
        )
        menu.addItem_(NSMenuItem.separatorItem())
        self._add(menu, "Quit Murphy", "doQuit:", "q")

        item.setMenu_(menu)
        self.status_item = item
        self.status_menu = menu

    @objc.python_method
    def _add(self, menu: NSMenu, title: str, action: str, key: str) -> NSMenuItem:
        entry = NSMenuItem.alloc().initWithTitle_action_keyEquivalent_(
            title, action, key
        )
        entry.setTarget_(self)
        menu.addItem_(entry)
        return entry

    def menuNeedsUpdate_(self, menu) -> None:
        """Enable/disable items each time the user opens the menu."""
        state = self.runtime.get_state()
        awaiting = state is AppState.AWAITING_CONFIRMATION
        idle = state is AppState.IDLE
        degraded = state is AppState.DEGRADED
        listening = state is AppState.LISTENING
        can_start_ptt = idle or awaiting

        self.ask_item.setEnabled_(idle)
        self.confirm_item.setEnabled_(awaiting)
        self.deny_item.setEnabled_(awaiting)
        self.start_item.setEnabled_(can_start_ptt and not listening)
        self.stop_item.setEnabled_(listening)
        self.clear_degraded_item.setEnabled_(degraded)

        root = load_project_root()
        root_label = str(root) if root is not None else "(not set)"
        self.status_detail_item.setTitle_(
            f"{self.runtime.status_message()} · root: {root_label}"
        )

    def refreshStatus_(self, _timer) -> None:
        if self.status_item is None:
            return
        title = _state_title(self.runtime.get_state())
        self.status_item.button().setTitle_(title)

    # --- Menu actions (UI thread only; runtime does the real work) ---

    def doStartPTT_(self, _sender) -> None:
        self.runtime.begin_ptt()
        self.refreshStatus_(None)

    def doStopPTT_(self, _sender) -> None:
        self.runtime.end_ptt()
        self.refreshStatus_(None)

    def doAsk_(self, _sender) -> None:
        if load_project_root() is None:
            _prompt_text(
                "Project root required",
                "Use Set Project Root… first, then Ask again.",
            )
            return
        text = _prompt_text("Ask Murphy", "What should Murphy do?")
        if text is None:
            return
        self.runtime.submit_text(text)
        self.refreshStatus_(None)

    def doConfirm_(self, _sender) -> None:
        pending = self.runtime.pending_confirmation()
        hint = pending.expected_phrase if pending is not None else "confirm <action>"
        phrase = _prompt_text(
            "Confirm action",
            f"Say the required phrase (example: {hint})",
        )
        if phrase is None:
            return
        self.runtime.submit_confirmation_phrase(phrase)
        self.refreshStatus_(None)

    def doDeny_(self, _sender) -> None:
        self.runtime.deny_confirmation()
        self.refreshStatus_(None)

    def doSetProjectRoot_(self, _sender) -> None:
        path = _choose_directory()
        if path is None:
            return
        self.runtime.set_project_root(path)

    def doShowLog_(self, _sender) -> None:
        if self.log_viewer is not None:
            self.log_viewer.show()

    def doClearDegraded_(self, _sender) -> None:
        self.runtime.clear_degraded()
        self.refreshStatus_(None)

    def doQuit_(self, _sender) -> None:
        NSApp.terminate_(None)


def run_menu(*, llm=None) -> int:
    """
    Build RuntimeController + NSApplication and enter the AppKit event loop.

    Returns after Quit (normally process exit via terminate).
    """
    client = llm if llm is not None else DeepSeekClient()
    runtime = RuntimeController(llm=client)
    app = NSApplication.sharedApplication()
    delegate = MenuBarApp.alloc().initWithRuntime_(runtime)
    app.setDelegate_(delegate)
    # Blocks until Quit; never returns on a normal quit path
    app.run()
    return 0


def main(argv: list[str] | None = None) -> int:
    """CLI helper used by `murphy menu`."""
    if sys.platform != "darwin":
        print("murphy menu requires macOS.", file=sys.stderr)
        return 1
    return run_menu()
