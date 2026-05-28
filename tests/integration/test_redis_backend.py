"""
Integration tests for the Redis storage backend.
Uses testcontainers to spin up a real Redis instance automatically.
No mocking — tests actual Redis commands and Lua scripts.

Run with: pytest tests/integration/ -v
Requires Docker to be running.
"""
import asyncio
import pytest
import pytest_asyncio

try:
    from testcontainers.redis import RedisContainer
    _TESTCONTAINERS_AVAILABLE = True
except ImportError:
    _TESTCONTAINERS_AVAILABLE = False

from agentskein.storage.redis_backend import RedisBackend
from agentskein.protocol.types import MemoryEntry, Branch, VectorClock
from agentskein.protocol.namespace import NamespaceConfig, NamespaceState

pytestmark = pytest.mark.skipif(
    not _TESTCONTAINERS_AVAILABLE,
    reason="testcontainers not installed"
)


@pytest.fixture(scope="module")
def redis_url():
    with RedisContainer("redis:7.2-alpine") as container:
        yield f"redis://{container.get_container_host_ip()}:{container.get_exposed_port(6379)}/0"


@pytest.fixture
async def backend(redis_url):
    b = RedisBackend(redis_url)
    yield b
    await b.close()


@pytest.mark.asyncio
async def test_save_and_get_namespace(backend):
    config = NamespaceConfig(name="test-ns", created_by="ci")
    state = NamespaceState(config=config)
    await backend.save_namespace(state)
    fetched = await backend.get_namespace("test-ns")
    assert fetched is not None
    assert fetched.config.name == "test-ns"


@pytest.mark.asyncio
async def test_save_and_get_entry(backend):
    entry = MemoryEntry(
        namespace="int-ns", branch="main", key="redis-key",
        value={"hello": "world"}, agent_id="ci-agent",
    )
    await backend.save_entry(entry)
    fetched = await backend.get_entry("int-ns", "main", "redis-key")
    assert fetched is not None
    assert fetched.value == {"hello": "world"}


@pytest.mark.asyncio
async def test_cow_fallthrough_redis(backend):
    """[B3] Child branch falls through to parent on Redis backend."""
    parent = MemoryEntry(
        namespace="cow-ns", branch="main", key="inherited",
        value="from_parent", agent_id="agent-A",
    )
    await backend.save_entry(parent)

    child_branch = Branch(
        name="child", namespace="cow-ns", parent_branch="main", created_by="agent-B"
    )
    await backend.save_branch("cow-ns", child_branch)

    fetched = await backend.get_entry("cow-ns", "child", "inherited")
    assert fetched is not None
    assert fetched.value == "from_parent"


@pytest.mark.asyncio
async def test_distributed_lock_redis(backend):
    """Lua-based atomic lock acquire / release on real Redis."""
    token = await backend.acquire_lock("my-resource")
    assert token is not None

    # Second acquire must fail
    token2 = await backend.acquire_lock("my-resource")
    assert token2 is None

    released = await backend.release_lock("my-resource", token)
    assert released is True

    # Can now re-acquire
    token3 = await backend.acquire_lock("my-resource")
    assert token3 is not None
    await backend.release_lock("my-resource", token3)


@pytest.mark.asyncio
async def test_branch_entries_ordered(backend):
    """get_branch_entries returns entries in creation order."""
    for i in range(5):
        entry = MemoryEntry(
            namespace="ord-ns", branch="main", key=f"key-{i}",
            value=i, agent_id="agent",
        )
        await backend.save_entry(entry)

    entries = await backend.get_branch_entries("ord-ns", "main")
    keys = [e.key for e in entries]
    assert keys == sorted(keys)   # sorted by creation time (ULID)
