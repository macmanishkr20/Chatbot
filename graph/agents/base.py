"""
AgentSpec + AgentRegistry — the contract for pluggable specialist agents.

Each agent module imports ``register_agent`` and calls it at import time.
The supervisor consumes the registry to:

  1. Render its routing prompt (one bullet per agent, sourced from
     ``AgentSpec.description``).
  2. Add each agent's sub-graph to the workflow as a worker node.
  3. Build the ``RouteResponse.next`` literal options.

Feature flags (``ENABLE_<AGENT_NAME>_AGENT``) gate registration. An agent
whose flag is set to ``"false"`` (default for new agents during rollout)
is skipped at boot — no prompt mention, no node, no routing.
"""
from __future__ import annotations

import logging
import os
from dataclasses import dataclass, field
from threading import RLock
from typing import Any, Callable, Iterable

logger = logging.getLogger(__name__)


# ── Special supervisor route — direct LLM reply, not an agent ──
AGENT_RESPOND = "RESPOND"


@dataclass(frozen=True)
class AgentSpec:
    """Immutable description of a specialist agent.

    Attributes:
      name: Unique identifier used in the supervisor's ``RouteResponse.next``
        literal and as the workflow node name. Must match ``[a-z][a-z0-9_]*``.
      description: One-paragraph routing hint shown to the supervisor LLM.
        First sentence should clearly state when to route here.
      build_subgraph: Async or sync callable that returns the compiled
        LangGraph sub-graph. Called once during supervisor compilation.
        Receives the optional shared memory ``store`` so the agent can use
        cross-session memory.
      sample_prompts: Optional list of canonical user phrasings — used in
        few-shot examples appended to the supervisor prompt.
      enabled_by_default: When False, the agent is registered but only
        activated if the corresponding ``ENABLE_<NAME>_AGENT`` env var is
        truthy. Useful for staged rollouts.
      requires_employee_context: When True, the agent expects
        ``employee_id`` / ``office_location`` in state — supervisor checks
        the auth user can resolve these before routing.
    """

    name: str
    description: str
    build_subgraph: Callable[..., Any]
    sample_prompts: tuple[str, ...] = field(default_factory=tuple)
    enabled_by_default: bool = True
    requires_employee_context: bool = False

    def __post_init__(self) -> None:
        if not self.name or not self.name.replace("_", "").isalnum() or not self.name[0].isalpha():
            raise ValueError(
                f"AgentSpec.name must be a valid identifier; got {self.name!r}",
            )
        if self.name == AGENT_RESPOND:
            raise ValueError(f"AgentSpec.name cannot be the reserved value {AGENT_RESPOND!r}")
        if not self.description.strip():
            raise ValueError("AgentSpec.description must not be empty")
        if not callable(self.build_subgraph):
            raise ValueError("AgentSpec.build_subgraph must be callable")


def _flag_enabled(agent_name: str, default: bool) -> bool:
    """Resolve ``ENABLE_<AGENT_NAME>_AGENT`` env flag.

    Truthy values: 1 / true / yes / on (case-insensitive).
    Missing var → ``default``.
    """
    raw = os.getenv(f"ENABLE_{agent_name.upper()}_AGENT")
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


class _AgentRegistry:
    """Thread-safe singleton holding all registered agents."""

    def __init__(self) -> None:
        self._specs: dict[str, AgentSpec] = {}
        self._lock = RLock()

    def register(self, spec: AgentSpec) -> None:
        with self._lock:
            if spec.name in self._specs:
                # Re-registering with the same callable is a no-op (helps with
                # hot-reload / repeated imports); a different spec is an error.
                existing = self._specs[spec.name]
                if existing is spec:
                    return
                raise ValueError(
                    f"Agent {spec.name!r} is already registered with a different spec.",
                )
            self._specs[spec.name] = spec
            logger.info("AgentRegistry: registered %r", spec.name)

    def unregister(self, name: str) -> None:
        with self._lock:
            self._specs.pop(name, None)

    def get(self, name: str) -> AgentSpec | None:
        with self._lock:
            return self._specs.get(name)

    def list(self, *, only_enabled: bool = True) -> list[AgentSpec]:
        """Return the registered specs.

        When ``only_enabled`` is True (default), env-flag-disabled agents are
        filtered out so the supervisor never sees them.
        """
        with self._lock:
            specs = list(self._specs.values())
        if not only_enabled:
            return specs
        return [
            s for s in specs
            if _flag_enabled(s.name, default=s.enabled_by_default)
        ]

    def names(self, *, only_enabled: bool = True) -> list[str]:
        return [s.name for s in self.list(only_enabled=only_enabled)]

    def descriptions(self, *, only_enabled: bool = True) -> Iterable[tuple[str, str]]:
        for s in self.list(only_enabled=only_enabled):
            yield s.name, s.description


AgentRegistry = _AgentRegistry()


def register_agent(spec: AgentSpec) -> None:
    """Public hook used by agent modules at import time."""
    AgentRegistry.register(spec)
