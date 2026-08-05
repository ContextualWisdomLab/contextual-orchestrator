"""Agent, policy-snapshot, and orchestrator-construction hooks."""

from __future__ import annotations

from typing import Any, Mapping

from .reasoning_control import ReasoningPolicy, ReasoningProfile
from ._reasoning_state import (
    _POLICY_OBJECTS,
    agent_reasoning_profile,
    configure_agent_reasoning,
    configure_orchestrator_reasoning,
)


def install_config_hooks(
    model_agent_type: type[Any],
    orchestrator_type: type[Any],
    policy_type: type[Any],
) -> None:
    """Install configuration round-trip and policy snapshot hooks."""
    original_agent_from_dict = model_agent_type.from_dict
    original_agent_to_config = model_agent_type.to_config
    original_policy_as_dict = policy_type.as_dict
    original_orchestrator_init = orchestrator_type.__init__

    def agent_from_dict(cls: type[Any], value: Mapping[str, Any]) -> Any:
        """Load normal agent fields plus an optional explicit reasoning profile."""
        if not isinstance(value, Mapping):
            return original_agent_from_dict(value)
        cleaned = dict(value)
        profile_data = cleaned.pop("reasoning_profile", None)
        agent = original_agent_from_dict(cleaned)
        if profile_data is not None:
            configure_agent_reasoning(agent, ReasoningProfile.from_dict(profile_data))
        return agent

    def agent_to_config(self: Any) -> dict[str, Any]:
        """Serialize the optional reasoning profile with the normal agent contract."""
        value = original_agent_to_config(self)
        profile = agent_reasoning_profile(self)
        if profile is not None:
            value["reasoning_profile"] = profile.to_dict()
        return value

    def policy_as_dict(self: Any) -> dict[str, Any]:
        """Include reasoning policy evidence in an orchestration policy snapshot."""
        value = original_policy_as_dict(self)
        policy = _POLICY_OBJECTS.get(self)
        if policy is not None:
            value["reasoning_control"] = policy.to_dict()
        return value

    def orchestrator_init(self: Any, *args: Any, reasoning_policy: Any = None, **kwargs: Any) -> None:
        """Initialize the core and attach an optional JSON or typed reasoning policy."""
        original_orchestrator_init(self, *args, **kwargs)
        if reasoning_policy is None:
            policy = ReasoningPolicy()
        elif isinstance(reasoning_policy, ReasoningPolicy):
            policy = reasoning_policy
        elif isinstance(reasoning_policy, Mapping):
            policy = ReasoningPolicy.from_dict(reasoning_policy)
        else:
            raise TypeError("reasoning_policy must be a mapping, ReasoningPolicy, or None")
        configure_orchestrator_reasoning(self, policy)


    model_agent_type.from_dict = classmethod(agent_from_dict)
    model_agent_type.to_config = agent_to_config
    model_agent_type.reasoning_profile = property(agent_reasoning_profile)
    policy_type.as_dict = policy_as_dict
    orchestrator_type.__init__ = orchestrator_init


__all__ = ["install_config_hooks"]
