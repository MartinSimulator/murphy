"""ConfirmationStore unit tests: digest binding, phrases, single-use, expiry."""

from __future__ import annotations

from datetime import timedelta
from pathlib import Path

import pytest

from murphy.execution.confirmation import (
    ConfirmationStatus,
    ConfirmationStore,
    expected_phrase_for,
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


def test_expected_phrases(project_root: Path) -> None:
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


def test_approve_correct_phrase_grants_once(project_root: Path) -> None:
    intent = _main_push(project_root)
    decision = classify(intent)
    store = ConfirmationStore()
    store.create(intent, decision)

    first = store.approve(intent.digest, "Confirm Push To Main")
    second = store.approve(intent.digest, "confirm push to main")

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

    result = store.approve(other.digest, "confirm push to main")

    assert result.status == ConfirmationStatus.unknown_digest


def test_expired_pending_cannot_approve(project_root: Path) -> None:
    intent = _main_push(project_root)
    store = ConfirmationStore()
    store.create(intent, classify(intent), ttl=timedelta(seconds=-1))

    result = store.approve(intent.digest, "confirm push to main")

    assert result.status == ConfirmationStatus.expired
