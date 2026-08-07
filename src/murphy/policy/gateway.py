# Gateway.py is the deterministic three-tier policy gate.
# It classifies a validated ActionIntent as auto_pass, confirm_required, or deny.
# It does not execute tools, prompt the user, or talk to the LLM.

from __future__ import annotations

from enum import Enum
from pathlib import Path
from typing import Any, Iterable, Mapping

import yaml
from pydantic import BaseModel, ConfigDict, Field

from murphy.policy.intent import ActionIntent

# Immutable, unordered set of keys that count as filesystem targets for scope checks
_PATH_ARG_KEYS = frozenset(
    {
        "path",
        "paths",
        "file",
        "files",
        "cwd",
        "directory",
        "dir",
        "folder",
        "target",
        "project",
        "project_path",
    }
)


# Enum for the possible tiers of a policy decision
# Used by PolicyDecision, PolicyConfig.tool_tiers, and classify when returning a tier
class PolicyTier(str, Enum):
    auto_pass = "auto_pass"
    confirm_required = "confirm_required"
    deny = "deny"

# Enum for the possible reasons for a policy decision
# Used by PolicyDecision.reason_code
class PolicyReason(str, Enum):
    tool_default = "TOOL_DEFAULT"
    unknown_tool = "UNKNOWN_TOOL"
    protected_branch = "PROTECTED_BRANCH"
    force_push = "FORCE_PUSH"
    deny_root = "DENY_ROOT"
    out_of_project = "OUT_OF_PROJECT"

# Result of classifying an ActionIntent; created by the classify function and helpers that return an early deny
# This is the shape that will be read by the orchestrator, audit journal, and tests
class PolicyDecision(BaseModel):
    model_config = ConfigDict(frozen=True)
    tier: PolicyTier
    reason_code: PolicyReason
    message: str
    intent_digest: str

# Frozen view of policy.defaults.yaml (deny roots, tool tiers, protected branches)
# Created by load_policy_config and cached in a global variable; used by the classify function and helpers
class PolicyConfig(BaseModel):
    model_config = ConfigDict(frozen=True)
    version: int = 1
    deny_roots: list[str] = Field(default_factory=list)
    tool_tiers: dict[str, PolicyTier] = Field(default_factory=dict)
    protected_branches: list[str] = Field(default_factory=list)

# default path to policy.defaults.yaml
def _default_policy_path() -> Path:
    # src/murphy/policy/gateway.py -> repo root is parents[3]
    return Path(__file__).resolve().parents[3] / "config" / "policy.defaults.yaml"

# Load the policy config from the given path defaulting to policy.defaults.yaml
def load_policy_config(path: Path | None = None) -> PolicyConfig:
    """Load checked-in policy defaults from YAML."""
    config_path = path or _default_policy_path()
    raw = yaml.safe_load(config_path.read_text(encoding="utf-8")) or {}
    return PolicyConfig.model_validate(raw)

# Cached policy config called by the classify function when no config is provided
_POLICY_CONFIG: PolicyConfig | None = None
def get_policy_config() -> PolicyConfig:
    global _POLICY_CONFIG
    if _POLICY_CONFIG is None:
        _POLICY_CONFIG = load_policy_config()
    return _POLICY_CONFIG

# Build "git.push style tool key from server and tool names 
# Used by classify and _elevate_git_push
def _tool_key(intent: ActionIntent) -> str:
    return f"{intent.server}.{intent.tool}"

# iterate over the path candidates and yield the string values
def _iter_path_candidates(args: Mapping[str, Any]) -> Iterable[str]:
    """Yield string values from known path-like argument keys."""
    # if the key is not in the PATH_ARG_KEYS, skip
    for key, value in args.items():
        if key not in _PATH_ARG_KEYS:
            continue
        # if the value is a string, yield it
        if isinstance(value, str):
            yield value
        # if the value is a list or tuple, iterate over the items and yield them
        elif isinstance(value, (list, tuple)):
            for item in value:
                if isinstance(item, str):
                    yield item

# Turn a config root like `/` or `~` into a Path
# Called by _is_denied_root_target
def _resolve_deny_root(root: str) -> Path:
    return Path(root).expanduser().resolve()

# True if the target hits a deny root with special case handling for `/` and `~`
# Called by _path_scope_decision
def _is_denied_root_target(target: Path, deny_roots: list[str]) -> bool:
    """
    Hard-deny dangerous roots from config.

    `/` and `~` only match the exact root path (otherwise every absolute path
    under `/`, or every project under home, would be denied).
    Other roots such as `/etc` deny the root and everything beneath it.
    """
    for root in deny_roots:
        denied = _resolve_deny_root(root)
        if denied == Path("/") or root in {"~", str(Path.home())}:
            if target == denied:
                return True
            continue
        if target == denied or denied in target.parents:
            return True
    return False

# Check path arguments for scope violations and return a deny decision if any do
# Called by classify
def _path_scope_decision(
    intent: ActionIntent,
    config: PolicyConfig,
) -> PolicyDecision | None:
    """Return a deny decision if any path arg violates scope rules."""
    project_root = intent.project_root.resolve()

    for raw_path in _iter_path_candidates(intent.args):
        target = Path(raw_path).expanduser().resolve()

        if _is_denied_root_target(target, config.deny_roots):
            return PolicyDecision(
                tier=PolicyTier.deny,
                reason_code=PolicyReason.deny_root,
                message=f"Path '{target}' targets a hard-denied root",
                intent_digest=intent.digest,
            )

        try:
            target.relative_to(project_root)
        except ValueError:
            return PolicyDecision(
                tier=PolicyTier.deny,
                reason_code=PolicyReason.out_of_project,
                message=(
                    f"Path '{target}' is outside project root '{project_root}'"
                ),
                intent_digest=intent.digest,
            )

    return None

# After the default tool tier, raise to confirm_required if force or protected branch is detected
def _elevate_git_push(
    intent: ActionIntent,
    config: PolicyConfig,
    tier: PolicyTier,
) -> tuple[PolicyTier, PolicyReason, str]:
    """Apply argument-sensitive confirm rules for git.push."""
    branch = str(intent.args.get("branch", ""))
    force = bool(intent.args.get("force", False))
    # if the force flag is set, return the confirm required tier and reason
    if force:
        return (
            PolicyTier.confirm_required,
            PolicyReason.force_push,
            f"Force push to '{branch}' requires confirmation",
        )
    # check if the branch is protected
    protected = {name.lower() for name in config.protected_branches}
    if branch.lower() in protected:
        return (
            PolicyTier.confirm_required,
            PolicyReason.protected_branch,
            f"Push to protected branch '{branch}' requires confirmation",
        )
    # return the default tier and reason
    return (
        tier,
        PolicyReason.tool_default,
        f"Tool '{_tool_key(intent)}' classified as {tier.value}",
    )

# classify the action intent
# this is the main public function that classifies the action intent
def classify(
    intent: ActionIntent,
    config: PolicyConfig | None = None,
) -> PolicyDecision:
    """
    Classify a canonical ActionIntent into auto_pass, confirm_required, or deny.

    Order: path hard-denies first, then tool default tier, then arg elevations.
    """
    policy = config or get_policy_config()

    path_decision = _path_scope_decision(intent, policy)
    if path_decision is not None:
        return path_decision

    key = _tool_key(intent)
    tier = policy.tool_tiers.get(key)
    if tier is None:
        return PolicyDecision(
            tier=PolicyTier.deny,
            reason_code=PolicyReason.unknown_tool,
            message=f"Unknown tool '{key}' is denied by policy",
            intent_digest=intent.digest,
        )

    reason = PolicyReason.tool_default
    message = f"Tool '{key}' classified as {tier.value}"

    if intent.server == "git" and intent.tool == "push":
        tier, reason, message = _elevate_git_push(intent, policy, tier)

    return PolicyDecision(
        tier=tier,
        reason_code=reason,
        message=message,
        intent_digest=intent.digest,
    )
