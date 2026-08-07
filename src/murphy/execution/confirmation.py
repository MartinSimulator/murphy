# confirmation.py holds digest-bound, single-use, short-lived pending approvals.
# The executor creates pendings on confirm_required; approve/deny never call tools.

from __future__ import annotations

import re
from datetime import datetime, timedelta, timezone
from enum import Enum

from pydantic import BaseModel, ConfigDict

from murphy.policy.gateway import PolicyDecision
from murphy.policy.intent import ActionIntent

_DEFAULT_TTL = timedelta(seconds=60)
_WHITESPACE = re.compile(r"\s+")


# Pending wait-state for one confirm-required ActionIntent
class PendingConfirmation(BaseModel):
    model_config = ConfigDict(frozen=True)
    intent: ActionIntent
    decision: PolicyDecision
    intent_digest: str
    expected_phrase: str
    created_at: datetime
    expires_at: datetime
    used: bool = False


# Outcome of an approve/deny attempt
class ConfirmationStatus(str, Enum):
    granted = "granted"
    denied = "denied"
    expired = "expired"
    phrase_mismatch = "phrase_mismatch"
    unknown_digest = "unknown_digest"
    already_used = "already_used"


# Result returned to the executor after the user responds
class ConfirmationResult(BaseModel):
    model_config = ConfigDict(frozen=True)
    status: ConfirmationStatus
    message: str
    intent_digest: str
    intent: ActionIntent | None = None


# Helper function to get the current UTC time
def _utcnow() -> datetime:
    return datetime.now(timezone.utc)
# 
# Helper function to normalize a phrase
def _normalize_phrase(phrase: str) -> str:
    return _WHITESPACE.sub(" ", phrase.strip().lower())


# Build an action-bound phrase from the intent (not the digest)
def expected_phrase_for(intent: ActionIntent) -> str:
    if intent.server == "git" and intent.tool == "push":
        branch = str(intent.args.get("branch", ""))
        if bool(intent.args.get("force", False)):
            return _normalize_phrase(f"confirm force push to {branch}")
        return _normalize_phrase(f"confirm push to {branch}")

    if intent.server == "docker" and intent.tool == "prune":
        return "confirm docker prune"

    return _normalize_phrase(f"confirm {intent.server} {intent.tool}")


# In-memory store of pending confirmations keyed by intent digest
class ConfirmationStore:
    def __init__(self) -> None:
        self._pending: dict[str, PendingConfirmation] = {}

    # Create a new pending confirmation
    def create(
        self,
        intent: ActionIntent,
        decision: PolicyDecision,
        *,
        ttl: timedelta = _DEFAULT_TTL,
    ) -> PendingConfirmation:
        if decision.intent_digest != intent.digest:
            raise ValueError("policy decision digest does not match intent digest")

        now = _utcnow()
        pending = PendingConfirmation(
            intent=intent,
            decision=decision,
            intent_digest=intent.digest,
            expected_phrase=expected_phrase_for(intent),
            created_at=now,
            expires_at=now + ttl,
            used=False,
        )
        self._pending[intent.digest] = pending
        return pending

    # Approve a pending confirmation
    def approve(self, digest: str, phrase: str) -> ConfirmationResult:
        pending = self._pending.get(digest)
        if pending is None:
            return ConfirmationResult(
                status=ConfirmationStatus.unknown_digest,
                message=f"No pending confirmation for digest '{digest}'",
                intent_digest=digest,
            )

        if pending.used:
            return ConfirmationResult(
                status=ConfirmationStatus.already_used,
                message=f"Confirmation for '{digest}' was already used",
                intent_digest=digest,
            )

        if pending.expires_at < _utcnow():
            self._pending.pop(digest, None)
            return ConfirmationResult(
                status=ConfirmationStatus.expired,
                message=f"Confirmation for '{digest}' expired at {pending.expires_at.isoformat()}",
                intent_digest=digest,
            )

        normalized = _normalize_phrase(phrase)
        if normalized in {"yes", "ok", "y", "yeah"} or normalized != pending.expected_phrase:
            return ConfirmationResult(
                status=ConfirmationStatus.phrase_mismatch,
                message=(
                    f"Expected '{pending.expected_phrase}', "
                    f"got '{normalized or phrase}'"
                ),
                intent_digest=digest,
            )

        # Frozen model: replace the entry instead of mutating .used
        self._pending[digest] = pending.model_copy(update={"used": True})
        return ConfirmationResult(
            status=ConfirmationStatus.granted,
            message=f"Confirmation granted for '{digest}'",
            intent_digest=digest,
            intent=pending.intent,
        )

    # Deny a pending confirmation
    def deny(self, digest: str) -> ConfirmationResult:
        pending = self._pending.get(digest)
        if pending is None:
            return ConfirmationResult(
                status=ConfirmationStatus.unknown_digest,
                message=f"No pending confirmation for digest '{digest}'",
                intent_digest=digest,
            )

        if pending.used:
            return ConfirmationResult(
                status=ConfirmationStatus.already_used,
                message=f"Confirmation for '{digest}' was already used",
                intent_digest=digest,
            )

        if pending.expires_at < _utcnow():
            self._pending.pop(digest, None)
            return ConfirmationResult(
                status=ConfirmationStatus.expired,
                message=f"Confirmation for '{digest}' expired at {pending.expires_at.isoformat()}",
                intent_digest=digest,
            )

        self._pending[digest] = pending.model_copy(update={"used": True})
        return ConfirmationResult(
            status=ConfirmationStatus.denied,
            message=f"Confirmation denied for '{digest}'",
            intent_digest=digest,
        )

    # Get a pending confirmation by digest
    def get(self, digest: str) -> PendingConfirmation | None:
        return self._pending.get(digest)

    # Clear expired pending confirmations
    def clear_expired(self) -> int:
        now = _utcnow()
        expired = [
            digest
            for digest, pending in self._pending.items()
            if pending.expires_at < now
        ]
        for digest in expired:
            del self._pending[digest]
        return len(expired)
