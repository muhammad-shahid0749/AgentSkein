"""
Unit tests for the InMemory storage backend.
No Redis required — tests pure Python logic including CoW branch fall-through.
"""
import pytest
import asyncio
from agentskein.storage.memory_backend import InMemoryBackend
from agentskein.protocol.types import MemoryEntry, Branch, VectorClock
from agentskein.protocol.namespace import NamespaceConfig, NamespaceState


@pytest.fixture
def backend():
    return InMemoryBackend()


@pytest.mark.asyncio
async def test_save_and_get_entry(backend):
    entry = MemoryEntry(
        namespace="ns1", branch="main", key="foo",
        value={"x": 1}, agent_id="agent-A",
    )
    await backend.save_entry(entry)
    fetched = await backend.get_entry("ns1", "main", "foo")
    assert fetched is not None
    assert fetched.value == {"x": 1}


@pytest.mark.asyncio
async def test_missing_entry_returns_none(backend):
    result = await backend.get_entry("ns1", "main", "does-not-exist")
    assert result is None


@pytest.mark.asyncio
async def test_delete_entry(backend):
    entry = MemoryEntry(
        namespace="ns1", branch="main", key="to-delete",
        value="bye", agent_id="agent-A",
    )
    await backend.save_entry(entry)
    deleted = await backend.delete_entry("ns1", "main", "to-delete")
    assert deleted is True
    assert await backend.get_entry("ns1", "main", "to-delete") is None


@pytest.mark.asyncio
async def test_cow_fallthrough_to_parent(backend):
    """[B3] Reading a key on a child branch falls through to parent if not found."""
    parent_entry = MemoryEntry(
        namespace="ns", branch="main", key="shared_key",
        value="parent_value", agent_id="agent-A",
    )
    await backend.save_entry(parent_entry)

    # Create a child branch pointing to "main" as parent
    child_branch = Branch(
        name="child",
        namespace="ns",
        parent_branch="main",
        created_by="agent-B",
    )
    await backend.save_branch("ns", child_branch)

    # Reading from child should fall through to main
    fetched = await backend.get_entry("ns", "child", "shared_key")
    assert fetched is not None
    assert fetched.value == "parent_value"


@pytest.mark.asyncio
async def test_cow_child_write_shadows_parent(backend):
    """[B3] Writing to child branch does NOT affect parent."""
    parent_entry = MemoryEntry(
        namespace="ns", branch="main", key="key",
        value="original", agent_id="agent-A",
    )
    await backend.save_entry(parent_entry)

    child_branch = Branch(name="child", namespace="ns", parent_branch="main", created_by="agent-B")
    await backend.save_branch("ns", child_branch)

    # Write a different value on the child branch
    child_entry = MemoryEntry(
        namespace="ns", branch="child", key="key",
        value="override", agent_id="agent-B",
    )
    await backend.save_entry(child_entry)

    # Child should see override
    assert (await backend.get_entry("ns", "child", "key")).value == "override"
    # Parent should still see original
    assert (await backend.get_entry("ns", "main", "key")).value == "original"


@pytest.mark.asyncio
async def test_distributed_lock_acquire_release(backend):
    token = await backend.acquire_lock("resource-x")
    assert token is not None

    # Second acquire should fail
    token2 = await backend.acquire_lock("resource-x")
    assert token2 is None

    # Release and re-acquire
    released = await backend.release_lock("resource-x", token)
    assert released is True

    token3 = await backend.acquire_lock("resource-x")
    assert token3 is not None


@pytest.mark.asyncio
async def test_lock_wrong_token_fails(backend):
    token = await backend.acquire_lock("resource-y")
    released = await backend.release_lock("resource-y", "wrong-token")
    assert released is False
    # Lock should still be held
    assert await backend.acquire_lock("resource-y") is None
