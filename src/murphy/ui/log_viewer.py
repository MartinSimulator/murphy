# log_viewer.py shows recent AuditJournal rows in a simple scrollable window.
# Read-only; does not call tools or the LLM.

from __future__ import annotations

import objc
from AppKit import (
    NSApp,
    NSBackingStoreBuffered,
    NSMakeRect,
    NSScrollView,
    NSTextView,
    NSViewHeightSizable,
    NSViewWidthSizable,
    NSWindow,
    NSWindowStyleMaskClosable,
    NSWindowStyleMaskMiniaturizable,
    NSWindowStyleMaskResizable,
    NSWindowStyleMaskTitled,
)
from Foundation import NSObject

from murphy.audit.journal import AuditJournal

# Helper function to format the recent rows for the log window
def format_recent_rows(rows: list) -> str:
    """Turn journal rows into plain text for the log window."""
    if not rows:
        return "No audit events yet."
    lines: list[str] = []
    for row in rows:
        tool_key = f"{row['server']}.{row['tool']}"
        outcome = row["outcome"] or "-"
        lines.append(
            f"{row['ts']}  {tool_key}  {row['policy_tier']}  {outcome}\n"
            f"  {row['policy_message']}"
        )
    return "\n\n".join(lines)

# Class to display the recent rows in a window
class LogViewerController(NSObject):
    """Own one NSWindow that displays fetch_recent() output."""

    journal = objc.ivar()
    window = objc.ivar()
    text_view = objc.ivar()

    def initWithJournal_(self, journal: AuditJournal):
        # PyObjC: call NSObject.init, then attach Python attributes
        self = objc.super(LogViewerController, self).init()
        if self is None:
            return None
        self.journal = journal
        self.window = None
        self.text_view = None
        return self

    @objc.python_method
    def show(self) -> None:
        if self.window is None:
            self._build_window()
        self.refresh()
        self.window.makeKeyAndOrderFront_(None)
        NSApp.activateIgnoringOtherApps_(True)

    @objc.python_method
    def refresh(self) -> None:
        if self.text_view is None:
            return
        text = format_recent_rows(self.journal.fetch_recent(100))
        self.text_view.setString_(text)

    @objc.python_method
    def _build_window(self) -> None:
        style = (
            NSWindowStyleMaskTitled
            | NSWindowStyleMaskClosable
            | NSWindowStyleMaskMiniaturizable
            | NSWindowStyleMaskResizable
        )
        window = NSWindow.alloc().initWithContentRect_styleMask_backing_defer_(
            NSMakeRect(200, 200, 640, 420),
            style,
            NSBackingStoreBuffered,
            False,
        )
        window.setTitle_("Murphy Audit Log")
        # Keep the Python wrapper alive when the user closes the window
        window.setReleasedWhenClosed_(False)

        scroll = NSScrollView.alloc().initWithFrame_(NSMakeRect(0, 0, 640, 420))
        scroll.setHasVerticalScroller_(True)
        scroll.setAutohidesScrollers_(True)
        scroll.setAutoresizingMask_(NSViewWidthSizable | NSViewHeightSizable)

        text_view = NSTextView.alloc().initWithFrame_(NSMakeRect(0, 0, 640, 420))
        text_view.setEditable_(False)
        text_view.setRichText_(False)
        text_view.setAutoresizingMask_(NSViewWidthSizable | NSViewHeightSizable)

        scroll.setDocumentView_(text_view)
        window.setContentView_(scroll)

        self.window = window
        self.text_view = text_view
