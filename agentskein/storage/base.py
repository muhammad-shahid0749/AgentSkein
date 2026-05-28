"""
Abstract storage backend protocol.
Every backend (Redis, InMemory, SQLite) must implement this interface.
Using Protocol instead of ABC so Rust backends can also conform.

[B3] All backends MUST implement lazy copy-on-write read fall-through:
  get_entry(namespace, branch, key) on a miss should look up the branch
  record, find its parent_branch, and retry with the parent (recursively
  up to the root "main" branch).  This is what makes O(1) fork() possible.
"""
from __future__ import annotations

from typing import Protocol, runtime_checkable

from ..protocol.namespace import NamespaceState
from ..protocol.types import Branch, MemoryEntry


@runtime_checkable
class StorageBackend(Protocol):

    async def get_namespace(self, name: str) -> NamespaceState | None: ...

    async def save_namespace(self, state: NamespaceState) -> None: ...

    async def get_entry(self, namespace: str, branch: str, key: str) -> MemoryEntry | None: ...

    async def save_entry(self, entry: MemoryEntry) -> None: ...

    async def get_branch_entries(self, namespace: str, branch: str) -> list[MemoryEntry]: ...

    async def get_branch(self, namespace: str, branch_name: str) -> Branch | None: ...

    async def save_branch(self, namespace: str, branch: Branch) -> None: ...

    async def delete_entry(self, namespace: str, branch: str, key: str) -> bool: ...

    async def acquire_lock(self, resource: str, ttl_ms: int = 2000) -> str | None:
        """
        Acquire a distributed lock on resource.
        Returns a lock token if acquired, None if already locked.
        ttl_ms: auto-release after this many milliseconds (safety valve).
        """
        ...

    async def release_lock(self, resource: str, token: str) -> bool: ...

    async def close(self) -> None: ...
