"""
quickstart.py — the file referenced by README.md "30-second quickstart".

This is the literal example from README.md lines 122–147, runnable as-is.
No Redis, no Rust required; uses InMemoryBackend.

Run:
    python quickstart.py
"""
import asyncio

from agentskein import AgentSkein
from agentskein.storage.memory_backend import InMemoryBackend


async def main() -> None:
    backend = InMemoryBackend()

    agent_a = AgentSkein("agent-A", "task-1", backend=backend)
    await agent_a.init()
    agent_b = AgentSkein("agent-B", "task-1", backend=backend)
    await agent_b.init()

    # Pattern A — disjoint keys, both preserved on main
    branch_a = await agent_a.fork("branch-A")
    branch_b = await agent_b.fork("branch-B")
    await branch_a.write("finding-from-A", {"source": "arxiv",   "topic": "CRDT"})
    await branch_b.write("finding-from-B", {"source": "neurips", "topic": "vector clocks"})
    await branch_a.merge_to("main")
    await branch_b.merge_to("main")

    snapshot = await agent_a.snapshot()
    print(f"Keys on main after both merges: {len(snapshot)}")
    for key, value in snapshot.items():
        print(f"  {key}: {value}")

    # Pattern-A claim from the README: every writer's contribution preserved.
    assert "finding-from-A" in snapshot, "finding-from-A missing on main"
    assert "finding-from-B" in snapshot, "finding-from-B missing on main"
    print("\nQuickstart PASSED: both findings present on main, zero data loss.")


if __name__ == "__main__":
    asyncio.run(main())
