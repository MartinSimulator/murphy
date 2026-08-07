# Journal.py is the SQLite audit log for proposed actions and policy decisions.
# One global DB file under Application Support; optional session_id groups rows.
# This module must not run SQL at import time - open the journal explicitly.

from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

from murphy.paths import USER_DATA_DIR
from murphy.policy.gateway import PolicyDecision
from murphy.policy.intent import ActionIntent

# default path to audit.db
DEFAULT_DB_PATH = USER_DATA_DIR / "audit.db"

# SQL to create the audit_events table
_CREATE_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS audit_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ts TEXT NOT NULL,
    session_id TEXT,
    intent_digest TEXT NOT NULL,
    server TEXT NOT NULL,
    tool TEXT NOT NULL,
    args_json TEXT NOT NULL,
    project_root TEXT NOT NULL,
    side_effect TEXT NOT NULL,
    policy_tier TEXT NOT NULL,
    policy_reason TEXT NOT NULL,
    policy_message TEXT NOT NULL,
    outcome TEXT,
    error TEXT,
    elapsed_ms INTEGER
)
"""

# AuditJournal is a context manager that opens and closes the audit journal database
class AuditJournal:
    """Append-oriented SQLite journal for ActionIntent + PolicyDecision records."""

    def __init__(self, db_path: Path | None = None) -> None:
        self.db_path = db_path or DEFAULT_DB_PATH # default to Application Support/Murphy/audit.db
        self.db_path.parent.mkdir(parents=True, exist_ok=True) # create the parent directory if it doesn't exist
        self._conn = sqlite3.connect(self.db_path) # connect to the database
        self._conn.row_factory = sqlite3.Row # access columns by name
        self._conn.execute(_CREATE_TABLE_SQL) # create the table if it doesn't exist
        self._conn.commit() # commit the transaction

    def close(self) -> None:
        """Close the audit journal database."""
        self._conn.close()

    def __enter__(self) -> AuditJournal:
        """Enter the context manager."""
        return self

    def __exit__(self, *args: object) -> None:
        """Exit the context manager."""
        self.close()

    # Record a proposal+decision row. Returns the new row id.
    def record_proposal(
        self,
        intent: ActionIntent,
        decision: PolicyDecision,
        *,
        session_id: str | None = None,
        outcome: str | None = "proposed",
    ) -> int:
        """Insert one proposal+decision row. Returns the new row id."""
        if decision.intent_digest != intent.digest:
            raise ValueError("policy decision digest does not match intent digest")

        ts = datetime.now(timezone.utc).isoformat()
        cur = self._conn.execute(
            """
            INSERT INTO audit_events (
                ts,
                session_id,
                intent_digest,
                server,
                tool,
                args_json,
                project_root,
                side_effect,
                policy_tier,
                policy_reason,
                policy_message,
                outcome
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            ( # bind values to the parameters
                ts,
                session_id,
                intent.digest,
                intent.server,
                intent.tool,
                json.dumps(dict(intent.args), sort_keys=True),
                str(intent.project_root),
                intent.side_effect.value,
                decision.tier.value,
                decision.reason_code.value,
                decision.message,
                outcome,
            ),
        )
        self._conn.commit() # commit the transaction
        return int(cur.lastrowid) # return the new row id

    # Return all rows for a given intent digest (newest last).
    def fetch_by_digest(self, intent_digest: str) -> list[sqlite3.Row]:
        """Return all rows for a given intent digest (newest last)."""
        cur = self._conn.execute(
            """
            SELECT * FROM audit_events
            WHERE intent_digest = ?
            ORDER BY id ASC
            """,
            (intent_digest,),
        )
        return list(cur.fetchall()) # return all the rows
