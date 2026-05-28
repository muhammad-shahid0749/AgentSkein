"""
Redis storage backend.

Key schema:
  mm:ns:{namespace}                    → NamespaceState JSON
  mm:entry:{namespace}:{branch}:{key}  → MemoryEntry JSON
  mm:branch:{namespace}:{branch_name}  → Branch JSON
  mm:lock:{resource}                   → lock token (with TTL)
  mm:idx:{namespace}:{branch}          → sorted set of entry keys (by timestamp)

[B3] get_entry() implements lazy copy-on-write fall-through to parent branch.
"""
from __future__ import annotations

import json
import secrets

import redis.asyncio as aioredis
from redis.asyncio import Redis

from ..protocol.namespace import NamespaceState
from ..protocol.types import Branch, MemoryEntry


class RedisBackend:
    PREFIX = "mm"

    def __init__(self, redis_url: str = "redis://localhost:6379/0"):
        self._url = redis_url
        self._redis: Redis | None = None

    async def _conn(self) -> Redis:
        if self._redis is None:
            self._redis = await aioredis.from_url(
                self._url,
                encoding="utf-8",
                decode_responses=True,
                max_connections=50,
            )
        return self._redis

    # ── Namespace ──────────────────────────────────────────────────────────────

    def _ns_key(self, name: str) -> str:
        return f"{self.PREFIX}:ns:{name}"

    async def get_namespace(self, name: str) -> NamespaceState | None:
        r = await self._conn()
        raw = await r.get(self._ns_key(name))
        if not raw:
            return None
        return NamespaceState.model_validate_json(raw)

    async def save_namespace(self, state: NamespaceState) -> None:
        r = await self._conn()
        await r.set(self._ns_key(state.config.name), state.model_dump_json())

    # ── Entries ────────────────────────────────────────────────────────────────

    def _entry_key(self, namespace: str, branch: str, key: str) -> str:
        return f"{self.PREFIX}:entry:{namespace}:{branch}:{key}"

    def _idx_key(self, namespace: str, branch: str) -> str:
        return f"{self.PREFIX}:idx:{namespace}:{branch}"

    async def get_entry(self, namespace: str, branch: str, key: str) -> MemoryEntry | None:
        r = await self._conn()
        raw = await r.get(self._entry_key(namespace, branch, key))
        if raw:
            return MemoryEntry.model_validate_json(raw)
        # [B3] Lazy CoW fall-through: look up parent branch and retry.
        branch_obj = await self.get_branch(namespace, branch)
        if branch_obj and branch_obj.parent_branch and branch_obj.parent_branch != branch:
            return await self.get_entry(namespace, branch_obj.parent_branch, key)
        return None

    async def save_entry(self, entry: MemoryEntry) -> None:
        r = await self._conn()
        ekey = self._entry_key(entry.namespace, entry.branch, entry.key)
        ikey = self._idx_key(entry.namespace, entry.branch)
        pipe = r.pipeline()
        raw = entry.model_dump_json()
        if entry.ttl_seconds:
            pipe.setex(ekey, entry.ttl_seconds, raw)
        else:
            pipe.set(ekey, raw)
        # Track in sorted index by creation time
        pipe.zadd(ikey, {entry.key: entry.created_at})
        await pipe.execute()

    async def get_branch_entries(self, namespace: str, branch: str) -> list[MemoryEntry]:
        r = await self._conn()
        keys = await r.zrange(self._idx_key(namespace, branch), 0, -1)
        if not keys:
            return []
        entry_keys = [self._entry_key(namespace, branch, k) for k in keys]
        raws = await r.mget(*entry_keys)
        return [
            MemoryEntry.model_validate_json(raw)
            for raw in raws if raw is not None
        ]

    async def delete_entry(self, namespace: str, branch: str, key: str) -> bool:
        r = await self._conn()
        pipe = r.pipeline()
        pipe.delete(self._entry_key(namespace, branch, key))
        pipe.zrem(self._idx_key(namespace, branch), key)
        results = await pipe.execute()
        return results[0] == 1

    # ── Branches ───────────────────────────────────────────────────────────────

    def _branch_key(self, namespace: str, branch_name: str) -> str:
        return f"{self.PREFIX}:branch:{namespace}:{branch_name}"

    async def get_branch(self, namespace: str, branch_name: str) -> Branch | None:
        r = await self._conn()
        raw = await r.get(self._branch_key(namespace, branch_name))
        if not raw:
            return None
        return Branch.model_validate_json(raw)

    async def save_branch(self, namespace: str, branch: Branch) -> None:
        r = await self._conn()
        await r.set(self._branch_key(namespace, branch.name), branch.model_dump_json())

    # ── Distributed Locking (Redlock single-node) ──────────────────────────────

    def _lock_key(self, resource: str) -> str:
        return f"{self.PREFIX}:lock:{resource}"

    async def acquire_lock(self, resource: str, ttl_ms: int = 2000) -> str | None:
        """
        SET NX PX — atomically set key only if it does not exist.
        Returns a unique token (used to verify ownership on release).
        """
        r = await self._conn()
        token = secrets.token_hex(16)
        acquired = await r.set(
            self._lock_key(resource),
            token,
            px=ttl_ms,    # TTL in milliseconds
            nx=True,      # Only set if not exists
        )
        return token if acquired else None

    async def release_lock(self, resource: str, token: str) -> bool:
        """
        Lua script for atomic check-and-delete:
        Only delete if the stored token matches ours (prevents releasing
        another agent's lock if our TTL expired mid-operation).
        """
        r = await self._conn()
        lua = """
        if redis.call('get', KEYS[1]) == ARGV[1] then
            return redis.call('del', KEYS[1])
        else
            return 0
        end
        """
        result = await r.eval(lua, 1, self._lock_key(resource), token)
        return result == 1

    async def close(self) -> None:
        if self._redis:
            await self._redis.aclose()
            self._redis = None
