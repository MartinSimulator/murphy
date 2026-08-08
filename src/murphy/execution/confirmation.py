# confirmation.py holds digest-bound, single-use, short-lived pending approvals.
# The executor creates pendings on confirm_required; approve/deny never call tools.
# Approval requires the codeword "confirm" plus an action token (e.g. push, prune).

from __future__ import annotations

import re
from datetime import datetime, timedelta, timezone
from enum import Enum

from pydantic import BaseModel, ConfigDict

from murphy.policy.gateway import PolicyDecision
from murphy.policy.intent import ActionIntent

_DEFAULT_TTL = timedelta(seconds=60)
# One wrong phrase is allowed; a second mismatch denies the pending confirmation
_MAX_CLARIFICATIONS = 1
_WHITESPACE = re.compile(r"\s+")
_CODEWORD = "confirm" # Codeword for the confirmation
_BARE_APPROVALS = frozenset({"yes", "ok", "y", "yeah"})


# Pending wait-state for one confirm-required ActionIntent
class PendingConfirmation(BaseModel):
    model_config = ConfigDict(frozen=True)
    intent: ActionIntent
    decision: PolicyDecision
    intent_digest: str
    # Full prompt for TTS / UI (what Murphy asks the user)
    expected_phrase: str
    # Tokens that must all appear as whole words in the user's reply
    required_tokens: tuple[str, ...]
    created_at: datetime
    expires_at: datetime
    used: bool = False
    # How many phrase mismatches have already been consumed (0 or 1)
    clarifications_used: int = 0


# Outcome of an approve/deny attempt
class ConfirmationStatus(str, Enum):
    granted = "granted"
    denied = "denied"
    expired = "expired"
    phrase_mismatch = "phrase_mismatch"  # wrong phrase; retry still allowed
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


# TTS / UI prompt describing the action (does not need to match the reply exactly)
def expected_phrase_for(intent: ActionIntent) -> str:
    if intent.server == "git" and intent.tool == "push":
        branch = str(intent.args.get("branch", ""))
        if bool(intent.args.get("force", False)):
            return _normalize_phrase(f"confirm force push to {branch}")
        return _normalize_phrase(f"confirm push to {branch}")

    if intent.server == "docker" and intent.tool == "prune":
        return "confirm docker prune"

    return _normalize_phrase(f"confirm {intent.server} {intent.tool}")


# Words the user must say (order does not matter; extras are allowed)
def required_tokens_for(intent: ActionIntent) -> tuple[str, ...]:
    if intent.server == "git" and intent.tool == "push":
        return (_CODEWORD, "push")

    if intent.server == "docker" and intent.tool == "prune":
        return (_CODEWORD, "prune")

    return (_CODEWORD, intent.tool)


# Helper function to check if a phrase satisfies the required tokens
def phrase_satisfies(phrase: str, required_tokens: tuple[str, ...]) -> bool:
    """True when the reply contains every required token as a whole word."""
    normalized = _normalize_phrase(phrase)
    if not normalized or normalized in _BARE_APPROVALS:
        return False
    words = set(normalized.split())
    return all(token in words for token in required_tokens)


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
            required_tokens=required_tokens_for(intent),
            created_at=now,
            expires_at=now + ttl,
            used=False,
            clarifications_used=0,
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
        tokens_hint = " and ".join(f"'{t}'" for t in pending.required_tokens)
        if not phrase_satisfies(phrase, pending.required_tokens):
            # First mismatch: keep pending open and allow one clarification
            if pending.clarifications_used < _MAX_CLARIFICATIONS:
                self._pending[digest] = pending.model_copy(
                    update={"clarifications_used": pending.clarifications_used + 1}
                )
                return ConfirmationResult(
                    status=ConfirmationStatus.phrase_mismatch,
                    message=(
                        f"Say {tokens_hint} (got '{normalized or phrase}'). "
                        "One clarification attempt remaining."
                    ),
                    intent_digest=digest,
                )

            # Second mismatch: consume the pending (treat as denial)
            self._pending[digest] = pending.model_copy(update={"used": True})
            return ConfirmationResult(
                status=ConfirmationStatus.denied,
                message=(
                    f"Say {tokens_hint} (got '{normalized or phrase}'). "
                    "No clarification attempts remaining."
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
