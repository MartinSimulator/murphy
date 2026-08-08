"""Side-effect catalog: load YAML and look up server.tool keys."""

from __future__ import annotations

from pathlib import Path

import pytest

from murphy.policy.intent import SideEffect
from murphy.policy.side_effects import load_side_effects, side_effect_for


def test_load_checked_in_side_effects() -> None:
    effects = load_side_effects()

    assert effects["git.status"] == SideEffect.read_only
    assert effects["git.push"] == SideEffect.mutative
    assert effects["docker.compose_up"] == SideEffect.additive
    assert effects["docker.prune"] == SideEffect.destructive


def test_side_effect_for_known_tools() -> None:
    assert side_effect_for("git", "status") == SideEffect.read_only
    assert side_effect_for("docker", "run_service") == SideEffect.additive


def test_side_effect_for_unknown_tool_raises() -> None:
    with pytest.raises(KeyError, match="unknown tool side effect"):
        side_effect_for("git", "rebase")


def test_load_side_effects_from_custom_path(tmp_path: Path) -> None:
    path = tmp_path / "side_effects.yaml"
    path.write_text(
        "version: 1\nside_effects:\n  git.status: read-only\n",
        encoding="utf-8",
    )

    effects = load_side_effects(path)

    assert effects == {"git.status": SideEffect.read_only}
