"""
AutoGen adapter.

Wraps AgentSkein as an AutoGen-compatible memory store.
Each ConversableAgent can read/write shared memory through its
AgentSkeinAgent wrapper.

Usage:
    from agentskein.adapters.autogen_adapter import AgentSkeinAgent
    import autogen

    mesh_agent = AgentSkeinAgent(
        name="researcher",
        namespace="project-x",
        system_message="You are a research assistant.",
        llm_config={"model": "gpt-4"},
    )
"""
from __future__ import annotations

from typing import Any

from ..client import AgentSkein, ConflictStrategy

try:
    import autogen
    _AUTOGEN_AVAILABLE = True
except ImportError:
    _AUTOGEN_AVAILABLE = False


class AgentSkeinStore:
    """
    A shared AgentSkein store that AutoGen agents can read/write.
    Pass one instance to multiple AgentSkeinAgent wrappers.
    """

    def __init__(
        self,
        namespace: str,
        redis_url: str = "redis://localhost:6379/0",
        conflict_strategy: ConflictStrategy = ConflictStrategy.MERGE_STRUCTURAL,
    ):
        self._namespace = namespace
        self._redis_url = redis_url
        self._strategy = conflict_strategy
        self._meshes: dict[str, AgentSkein] = {}

    def get_mesh(self, agent_name: str) -> AgentSkein:
        if agent_name not in self._meshes:
            self._meshes[agent_name] = AgentSkein(
                agent_id=agent_name,
                namespace=self._namespace,
                redis_url=self._redis_url,
                conflict_strategy=self._strategy,
            )
        return self._meshes[agent_name]

    async def remember(self, agent_name: str, key: str, value: Any) -> None:
        """Write a fact to shared memory."""
        mesh = self.get_mesh(agent_name)
        await mesh.init()
        await mesh.write(key, value)

    async def recall(self, agent_name: str, key: str) -> Any | None:
        """Read a fact from shared memory."""
        mesh = self.get_mesh(agent_name)
        await mesh.init()
        return await mesh.read(key)

    async def recall_all(self, agent_name: str) -> dict[str, Any]:
        """Return all known facts for this agent."""
        mesh = self.get_mesh(agent_name)
        await mesh.init()
        return await mesh.snapshot()
