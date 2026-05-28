"""
In-memory storage backend for unit tests and development.
Thread-safe via asyncio.Lock. Not suitable for multi-process use.

[B3] get_entry() implements lazy copy-on-write fall-through to parent branch.
"""
from __future__ import annotations

import asyncio
import secrets

from ..protocol.namespace import NamespaceState
from ..protocol.types import Branch, MemoryEntry


class InMemoryBackend:
    def __init__(self) -> None:
        self._namespaces: dict[str, NamespaceState] = {}
        self._entries: dict[str, MemoryEntry] = {}        # "ns:branch:key" → entry
        self._branches: dict[str, Branch] = {}            # "ns:branch" → branch
        self._locks: dict[str, str] = {}                  # resource → token
        self._lock = asyncio.Lock()

    def _ekey(self, ns: str, branch: str, key: str) -> str:
        return f"{ns}:{branch}:{key}"

    async def get_namespace(self, name: str) -> NamespaceState | None:
        return self._namespaces.get(name)

    async def save_namespace(self, state: NamespaceState) -> None:
        self._namespaces[state.config.name] = state

    async def get_entry(self, namespace: str, branch: str, key: str) -> MemoryEntry | None:
        entry = self._entries.get(self._ekey(namespace, branch, key))
        if entry is not None:
            return entry
        # [B3] Lazy CoW fall-through to parent branch
        branch_obj = self._branches.get(f"{namespace}:{branch}")
        if branch_obj and branch_obj.parent_branch and branch_obj.parent_branch != branch:
            return await self.get_entry(namespace, branch_obj.parent_branch, key)
        return None

    async def save_entry(self, entry: MemoryEntry) -> None:
        self._entries[self._ekey(entry.namespace, entry.branch, entry.key)] = entry

    async def get_branch_entries(self, namespace: str, branch: str) -> list[MemoryEntry]:
        prefix = f"{namespace}:{branch}:"
        return [e for k, e in self._entries.items() if k.startswith(prefix)]

    async def get_branch(self, namespace: str, branch_name: str) -> Branch | None:
        return self._branches.get(f"{namespace}:{branch_name}")

    async def save_branch(self, namespace: str, branch: Branch) -> None:
        self._branches[f"{namespace}:{branch.name}"] = branch

    async def delete_entry(self, namespace: str, branch: str, key: str) -> bool:
        return self._entries.pop(self._ekey(namespace, branch, key), None) is not None

    async def acquire_lock(self, resource: str, ttl_ms: int = 2000) -> str | None:
        async with self._lock:
            if resource in self._locks:
                return None
            token = secrets.token_hex(16)
            self._locks[resource] = token
            return token

    async def release_lock(self, resource: str, token: str) -> bool:
        async with self._lock:
            if self._locks.get(resource) == token:
                del self._locks[resource]
                return True
            return False

    async def close(self) -> None:
        self._entries.clear()
        self._namespaces.clear()
        self._branches.clear()
