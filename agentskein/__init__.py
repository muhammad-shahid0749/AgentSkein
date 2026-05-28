"""
AgentSkein — cross-agent shared memory with Git-semantics and conflict resolution.

Quick start:
    from agentskein import AgentSkein, ConflictStrategy

    async with AgentSkein(agent_id="agent-1", namespace="my-task") as mesh:
        await mesh.write("result", {"answer": 42})
        value = await mesh.read("result")

    # Two agents, conflict-free merge
    mesh_a = AgentSkein(agent_id="agent-a", namespace="shared")
    mesh_b = AgentSkein(agent_id="agent-b", namespace="shared")
    await mesh_a.init()
    await mesh_b.init()

    branch_a = await mesh_a.fork("branch-a")
    branch_b = await mesh_b.fork("branch-b")

    await branch_a.write("step1", {"task": "research"})   # disjoint top-level keys
    await branch_b.write("step2", {"task": "write"})

    await branch_a.merge_to("main")
    await branch_b.merge_to("main")
    # Result on main: {"step1": {...}, "step2": {...}}  ← clean 3-way merge
"""
from .client import AgentSkein, ConflictDetectedError
from .protocol.namespace import NamespaceConfig, NamespaceState
from .protocol.types import (
    Branch,
    Conflict,
    ConflictStrategy,
    MemoryEntry,
    Resolution,
    VectorClock,
)
from .storage.memory_backend import InMemoryBackend
from .storage.redis_backend import RedisBackend
from .storage.sqlite_backend import SQLiteBackend

# Backwards-compatibility alias so existing user code using the old name
# keeps working until they migrate their imports. New code should use AgentSkein.
MemoryMesh = AgentSkein

__all__ = [
    "AgentSkein",
    "MemoryMesh",          # deprecated alias
    "ConflictDetectedError",
    "MemoryEntry",
    "Branch",
    "Conflict",
    "Resolution",
    "VectorClock",
    "ConflictStrategy",
    "NamespaceConfig",
    "NamespaceState",
    "InMemoryBackend",
    "RedisBackend",
    "SQLiteBackend",
]

__version__ = "0.1.0"
