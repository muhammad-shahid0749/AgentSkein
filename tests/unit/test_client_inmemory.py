"""
Unit tests for the AgentSkein client using InMemoryBackend.
Full write-conflict-resolve cycle tested without Redis or Rust.
"""
import pytest
import asyncio
from agentskein import AgentSkein, ConflictStrategy, ConflictDetectedError
from agentskein.storage.memory_backend import InMemoryBackend


@pytest.fixture
def backend():
    return InMemoryBackend()


@pytest.mark.asyncio
async def test_basic_write_and_read(backend):
    mesh = AgentSkein("agent-1", "ns1", backend=backend)
    await mesh.init()
    await mesh.write("greeting", "hello")
    result = await mesh.read("greeting")
    assert result == "hello"


@pytest.mark.asyncio
async def test_write_updates_local_clock(backend):
    mesh = AgentSkein("agent-1", "ns1", backend=backend)
    await mesh.init()
    await mesh.write("k", 42)
    assert mesh._local_clock.clocks.get("agent-1", 0) >= 1


@pytest.mark.asyncio
async def test_read_updates_local_clock(backend):
    """Reading an entry should absorb its clock into our local clock."""
    writer = AgentSkein("writer", "ns1", backend=backend)
    reader = AgentSkein("reader", "ns1", backend=backend)
    await writer.init()
    await reader.init()

    await writer.write("data", {"value": 99})
    await reader.read("data")
    # After reading, reader should know writer's clock
    assert reader._local_clock.clocks.get("writer", 0) >= 1


@pytest.mark.asyncio
async def test_no_conflict_causal_sequence(backend):
    """Agent-B reads then writes — no conflict since it has the latest clock."""
    mesh_a = AgentSkein("agent-A", "shared", backend=backend)
    mesh_b = AgentSkein("agent-B", "shared", backend=backend)
    await mesh_a.init()
    await mesh_b.init()

    await mesh_a.write("status", "idle")
    # B reads first (absorbs A's clock)
    await mesh_b.read("status")
    # Now B writes — should be causally ordered, no conflict
    entry = await mesh_b.write("status", "busy")
    assert entry.value == "busy"


@pytest.mark.asyncio
async def test_conflict_raises_with_raise_strategy(backend):
    """Two agents writing the same key concurrently with RAISE strategy."""
    mesh_a = AgentSkein("agent-A", "shared", backend=backend,
                        conflict_strategy=ConflictStrategy.RAISE)
    mesh_b = AgentSkein("agent-B", "shared", backend=backend,
                        conflict_strategy=ConflictStrategy.RAISE)
    await mesh_a.init()
    await mesh_b.init()

    # A writes first
    await mesh_a.write("key", "value-A")
    # B writes without reading (concurrent) — should raise
    with pytest.raises(ConflictDetectedError) as exc_info:
        await mesh_b.write("key", "value-B")
    assert exc_info.value.conflict.key == "key"


@pytest.mark.asyncio
async def test_conflict_last_write_wins(backend):
    mesh_a = AgentSkein("agent-A", "shared", backend=backend,
                        conflict_strategy=ConflictStrategy.LAST_WRITE_WINS)
    mesh_b = AgentSkein("agent-B", "shared", backend=backend,
                        conflict_strategy=ConflictStrategy.LAST_WRITE_WINS)
    await mesh_a.init()
    await mesh_b.init()

    await mesh_a.write("key", "A")
    await mesh_b.write("key", "B")  # B's value wins (last write)
    result = await mesh_b.read("key")
    assert result == "B"


@pytest.mark.asyncio
async def test_conflict_first_write_wins(backend):
    mesh_a = AgentSkein("agent-A", "shared", backend=backend,
                        conflict_strategy=ConflictStrategy.FIRST_WRITE_WINS)
    mesh_b = AgentSkein("agent-B", "shared", backend=backend,
                        conflict_strategy=ConflictStrategy.FIRST_WRITE_WINS)
    await mesh_a.init()
    await mesh_b.init()

    await mesh_a.write("key", "first")
    await mesh_b.write("key", "second")
    result = await mesh_b.read("key")
    assert result == "first"  # A's value preserved


@pytest.mark.asyncio
async def test_structural_merge_no_rust(backend):
    """
    Structural merge without Rust (Python fallback: dict merge).
    Tests that the merge path runs without error.
    """
    mesh_a = AgentSkein("agent-A", "shared", backend=backend,
                        conflict_strategy=ConflictStrategy.MERGE_STRUCTURAL)
    mesh_b = AgentSkein("agent-B", "shared", backend=backend,
                        conflict_strategy=ConflictStrategy.MERGE_STRUCTURAL)
    await mesh_a.init()
    await mesh_b.init()

    await mesh_a.write("profile", {"name": "Alice", "role": "researcher"})
    await mesh_b.write("profile", {"name": "Alice", "score": 99})
    result = await mesh_b.read("profile")
    assert result is not None  # merge produced some result


@pytest.mark.asyncio
async def test_fork_and_read_parent_entry(backend):
    """[B3] Forked branch can read entries from parent without copying them."""
    mesh = AgentSkein("agent-1", "ns", backend=backend)
    await mesh.init()
    await mesh.write("shared", "parent_value")

    forked = await mesh.fork("feature-branch")
    result = await forked.read("shared")
    assert result == "parent_value"   # falls through to parent


@pytest.mark.asyncio
async def test_fork_write_does_not_affect_parent(backend):
    """[B3] Writing on fork branch doesn't change parent."""
    mesh = AgentSkein("agent-1", "ns2", backend=backend)
    await mesh.init()
    await mesh.write("key", "original")

    forked = await mesh.fork("branch-x")
    await forked.write("key", "forked_value")

    parent_value = await mesh.read("key")
    assert parent_value == "original"

    fork_value = await forked.read("key")
    assert fork_value == "forked_value"


@pytest.mark.asyncio
async def test_merge_to_main(backend):
    """Merging a branch back to main produces the combined result."""
    mesh = AgentSkein("agent-1", "ns3", backend=backend)
    await mesh.init()
    await mesh.write("a", 1)

    branch = await mesh.fork("work-branch")
    await branch.write("b", 2)

    summary = await branch.merge_to("main")
    assert "b" in summary["merged_keys"]

    result = await mesh.read("b")
    assert result == 2


@pytest.mark.asyncio
async def test_snapshot(backend):
    mesh = AgentSkein("agent-1", "snap-ns", backend=backend)
    await mesh.init()
    await mesh.write("x", 10)
    await mesh.write("y", 20)
    snap = await mesh.snapshot()
    assert snap == {"x": 10, "y": 20}


@pytest.mark.asyncio
async def test_delete(backend):
    mesh = AgentSkein("agent-1", "del-ns", backend=backend)
    await mesh.init()
    await mesh.write("temp", "gone")
    deleted = await mesh.delete("temp")
    assert deleted is True
    assert await mesh.read("temp") is None


@pytest.mark.asyncio
async def test_context_manager(backend):
    async with AgentSkein("agent-1", "ctx-ns", backend=backend) as mesh:
        await mesh.write("key", "value")
        assert await mesh.read("key") == "value"


@pytest.mark.asyncio
async def test_embedding_fn_called_on_write(backend):
    """[B8] embedding_fn should be called and populate entry.embedding."""
    recorded = []

    async def fake_embed(value):
        recorded.append(value)
        return [0.1, 0.2, 0.3]

    mesh = AgentSkein("agent-1", "emb-ns", backend=backend, embedding_fn=fake_embed)
    await mesh.init()
    await mesh.write("doc", "hello world")

    assert len(recorded) == 1
    entry = await mesh.read_entry("doc")
    assert entry is not None
    assert entry.embedding == [0.1, 0.2, 0.3]


@pytest.mark.asyncio
async def test_semantic_merge_uses_llm(backend):
    """[B11] MERGE_SEMANTIC should call llm_merge_fn when provided."""
    calls = []

    async def fake_llm(prompt: str) -> str:
        calls.append(prompt)
        return "merged text"

    mesh_a = AgentSkein("agent-A", "sem-ns", backend=backend,
                        conflict_strategy=ConflictStrategy.MERGE_SEMANTIC,
                        llm_merge_fn=fake_llm)
    mesh_b = AgentSkein("agent-B", "sem-ns", backend=backend,
                        conflict_strategy=ConflictStrategy.MERGE_SEMANTIC,
                        llm_merge_fn=fake_llm)
    await mesh_a.init()
    await mesh_b.init()

    await mesh_a.write("text", "version A text")
    await mesh_b.write("text", "version B text")

    # LLM should have been called for the conflict
    assert len(calls) >= 1
    result = await mesh_b.read("text")
    assert result == "merged text"
