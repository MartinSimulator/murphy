"""ConfirmationStore unit tests: digest binding, tokens, single-use, expiry."""

from __future__ import annotations

from datetime import timedelta
from pathlib import Path

import pytest

from murphy.execution.confirmation import (
    ConfirmationStatus,
    ConfirmationStore,
    expected_phrase_for,
    phrase_satisfies,
    required_tokens_for,
)
from murphy.policy.gateway import classify
from murphy.policy.intent import SideEffect, build_validated_action_intent


@pytest.fixture
def project_root(tmp_path: Path) -> Path:
    root = tmp_path / "my-project"
    root.mkdir()
    return root


def _main_push(project_root: Path):
    return build_validated_action_intent(
        server="git",
        tool="push",
        args={"remote": "origin", "branch": "main", "force": False},
        project_root=project_root,
        side_effect=SideEffect.mutative,
    )


def test_prompt_and_required_tokens(project_root: Path) -> None:
    main = _main_push(project_root)
    force = build_validated_action_intent(
        server="git",
        tool="push",
        args={"remote": "origin", "branch": "feature", "force": True},
        project_root=project_root,
        side_effect=SideEffect.destructive,
    )
    prune = build_validated_action_intent(
        server="docker",
        tool="prune",
        args={"all": True, "volumes": True},
        project_root=project_root,
        side_effect=SideEffect.destructive,
    )

    assert expected_phrase_for(main) == "confirm push to main"
    assert expected_phrase_for(force) == "confirm force push to feature"
    assert expected_phrase_for(prune) == "confirm docker prune"
    assert required_tokens_for(main) == ("confirm", "push")
    assert required_tokens_for(force) == ("confirm", "push")
    assert required_tokens_for(prune) == ("confirm", "prune")


def test_phrase_satisfies_requires_codeword_and_action_token() -> None:
    tokens = ("confirm", "push")
    assert phrase_satisfies("confirm push", tokens)
    assert phrase_satisfies("yes please confirm the push to main", tokens)
    assert not phrase_satisfies("confirm", tokens)
    assert not phrase_satisfies("push", tokens)
    assert not phrase_satisfies("yes", tokens)
    assert not phrase_satisfies("ok", tokens)


def test_approve_short_confirm_push_grants_once(project_root: Path) -> None:
    intent = _main_push(project_root)
    decision = classify(intent)
    store = ConfirmationStore()
    store.create(intent, decision)

    first = store.approve(intent.digest, "confirm push")
    second = store.approve(intent.digest, "confirm push")

    assert first.status == ConfirmationStatus.granted
    assert first.intent is not None
    assert first.intent.digest == intent.digest
    assert second.status == ConfirmationStatus.already_used


def test_digest_a_cannot_approve_digest_b(project_root: Path) -> None:
    intent = _main_push(project_root)
    other = build_validated_action_intent(
        server="git",
        tool="push",
        args={"remote": "origin", "branch": "master", "force": False},
        project_root=project_root,
        side_effect=SideEffect.mutative,
    )
    store = ConfirmationStore()
    store.create(intent, classify(intent))

    result = store.approve(other.digest, "confirm push")

    assert result.status == ConfirmationStatus.unknown_digest


def test_expired_pending_cannot_approve(project_root: Path) -> None:
    intent = _main_push(project_root)
    store = ConfirmationStore()
    store.create(intent, classify(intent), ttl=timedelta(seconds=-1))

    result = store.approve(intent.digest, "confirm push")

    assert result.status == ConfirmationStatus.expired


def test_first_phrase_mismatch_allows_clarification(project_root: Path) -> None:
    intent = _main_push(project_root)
    store = ConfirmationStore()
    store.create(intent, classify(intent))

    first = store.approve(intent.digest, "yes")
    pending = store.get(intent.digest)
    second = store.approve(intent.digest, "confirm push")

    assert first.status == ConfirmationStatus.phrase_mismatch
    assert pending is not None
    assert pending.clarifications_used == 1
    assert not pending.used
    assert second.status == ConfirmationStatus.granted


def test_second_phrase_mismatch_denies(project_root: Path) -> None:
    intent = _main_push(project_root)
    store = ConfirmationStore()
    store.create(intent, classify(intent))

    first = store.approve(intent.digest, "yes")
    second = store.approve(intent.digest, "confirm")
    third = store.approve(intent.digest, "confirm push")

    assert first.status == ConfirmationStatus.phrase_mismatch
    assert second.status == ConfirmationStatus.denied
    assert third.status == ConfirmationStatus.already_used


def test_prune_requires_confirm_and_prune(project_root: Path) -> None:
    intent = build_validated_action_intent(
        server="docker",
        tool="prune",
        args={"all": True, "volumes": True},
        project_root=project_root,
        side_effect=SideEffect.destructive,
    )
    store = ConfirmationStore()
    store.create(intent, classify(intent))

    assert store.approve(intent.digest, "confirm").status == ConfirmationStatus.phrase_mismatch
    assert store.approve(intent.digest, "confirm prune please").status == ConfirmationStatus.granted
