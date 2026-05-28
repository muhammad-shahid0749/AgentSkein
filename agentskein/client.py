"""
AgentSkein — main client class.

Usage:
    mesh = AgentSkein(agent_id="researcher-1", namespace="task-42")
    await mesh.write("finding", {"url": "...", "summary": "..."})
    value = await mesh.read("finding")

    # Branching workflow
    branch = await mesh.fork("my-branch")
    await branch.write("draft", {"text": "..."})
    await branch.merge_to("main")

    # With embedding and LLM merge support
    mesh = AgentSkein(
        agent_id="agent-1",
        namespace="task-42",
        embedding_fn=my_embed_fn,   # async (value) → list[float]  [B8]
        llm_merge_fn=my_llm_fn,     # async (prompt) → str          [B11]
    )
"""
from __future__ import annotations

import asyncio
import json
import random
import time
from collections.abc import Awaitable, Callable
from typing import Any

import structlog

from .protocol.namespace import NamespaceConfig, NamespaceState
from .protocol.semantic_merge import LLMMergeCallable
from .protocol.types import (
    Branch,
    Conflict,
    ConflictStrategy,
    MemoryEntry,
    VectorClock,
)
from .storage.base import StorageBackend
from .storage.redis_backend import RedisBackend

# Rust extension — imported lazily so the package is importable even
# before `maturin develop` has been run (e.g. in type-check only mode).
try:
    from ._core import py_three_way_merge  # type: ignore[import]
    _RUST_AVAILABLE = True
except ImportError:
    _RUST_AVAILABLE = False
    py_three_way_merge = None  # type: ignore[assignment]

log = structlog.get_logger(__name__)

EmbeddingFn = Callable[[Any], Awaitable[list[float]]]


class ConflictDetectedError(Exception):
    """Raised when strategy=RAISE and a conflict is found."""
    def __init__(self, conflict: Conflict):
        self.conflict = conflict
        super().__init__(
            f"Write conflict at key='{conflict.key}' in namespace='{conflict.namespace}'"
        )


class AgentSkein:
    """
    The main entry point for agents interacting with shared memory.

    Each agent instantiates its own AgentSkein with a unique agent_id.
    Multiple agents can share the same namespace.
    """

    def __init__(
        self,
        agent_id: str,
        namespace: str,
        branch: str = "main",
        backend: StorageBackend | None = None,
        redis_url: str = "redis://localhost:6379/0",
        conflict_strategy: ConflictStrategy = ConflictStrategy.MERGE_STRUCTURAL,
        lock_timeout_ms: int = 3000,
        embedding_fn: EmbeddingFn | None = None,
        llm_merge_fn: LLMMergeCallable | None = None,
    ):
        """
        embedding_fn: optional async callable (value) → list[float].
            Called on every write to populate entry.embedding.  [B8]

        llm_merge_fn: optional async callable (prompt: str) → str.
            Used by MERGE_SEMANTIC strategy. Falls back to structural
            merge if None.  [B11]
        """
        self.agent_id = agent_id
        self.namespace_name = namespace
        self.branch_name = branch
        self._strategy = conflict_strategy
        self._lock_timeout_ms = lock_timeout_ms
        self._backend: StorageBackend = backend or RedisBackend(redis_url)
        self._local_clock = VectorClock()
        self._embedding_fn = embedding_fn   # [B8]
        self._llm_merge_fn = llm_merge_fn   # [B11]

    # ── Initialisation ─────────────────────────────────────────────────────────

    async def init(self, config: NamespaceConfig | None = None) -> None:
        """
        Initialise the namespace if it doesn't exist yet.
        Idempotent — safe to call from multiple agents simultaneously.
        """
        existing = await self._backend.get_namespace(self.namespace_name)
        if existing is None:
            if config is None:
                config = NamespaceConfig(
                    name=self.namespace_name,
                    created_by=self.agent_id,
                )
            state = NamespaceState(config=config)
            # Create main branch
            main_branch = Branch(
                name="main",
                namespace=self.namespace_name,
                parent_branch="main",
                created_by=self.agent_id,
            )
            state.add_branch(main_branch)
            await self._backend.save_namespace(state)
            await self._backend.save_branch(self.namespace_name, main_branch)
            log.info("namespace.created", namespace=self.namespace_name, agent=self.agent_id)

    # ── Read ───────────────────────────────────────────────────────────────────

    async def read(self, key: str) -> Any | None:
        """
        Read a value from the current branch.
        Updates local vector clock to reflect this read (causal ordering).
        """
        entry = await self._backend.get_entry(
            self.namespace_name, self.branch_name, key
        )
        if entry is None:
            return None
        # Merge entry's clock into ours so we know we've seen this version
        self._local_clock = self._local_clock.merge(entry.clock)
        return entry.value

    async def read_entry(self, key: str) -> MemoryEntry | None:
        """Read the full MemoryEntry (with metadata, clock, agent attribution)."""
        return await self._backend.get_entry(
            self.namespace_name, self.branch_name, key
        )

    # ── Write (with conflict detection + resolution) ───────────────────────────

    async def write(
        self,
        key: str,
        value: Any,
        tags: list[str] | None = None,
        ttl_seconds: int | None = None,
        strategy: ConflictStrategy | None = None,
    ) -> MemoryEntry:
        """
        Write a value to shared memory with full conflict detection.

        Flow:
          1. Acquire distributed lock on this key  (with exponential backoff [B4])
          2. Read the current value (if any)
          3. Check if our clock and the stored clock are concurrent (conflict)
          4. If conflict → resolve per strategy
          5. Write resolved value with merged clock (storing base_value [B1])
          6. Populate embedding if embedding_fn provided  [B8]
          7. Release lock
        """
        effective_strategy = strategy or self._strategy
        lock_resource = f"{self.namespace_name}:{self.branch_name}:{key}"

        # [B4] Exponential backoff with jitter — avoids thundering herd
        token = None
        max_attempts = 6
        for attempt in range(max_attempts):
            token = await self._backend.acquire_lock(
                lock_resource, ttl_ms=self._lock_timeout_ms
            )
            if token is not None:
                break
            if attempt < max_attempts - 1:
                delay = (0.02 * (2 ** attempt)) + random.uniform(0, 0.01)
                await asyncio.sleep(delay)

        if token is None:
            raise TimeoutError(
                f"Could not acquire lock for '{key}' after {max_attempts} attempts. "
                "Another agent may be writing to this key."
            )

        try:
            return await self._do_write(
                key, value, tags, ttl_seconds, effective_strategy
            )
        finally:
            await self._backend.release_lock(lock_resource, token)

    async def _do_write(
        self,
        key: str,
        value: Any,
        tags: list[str] | None,
        ttl_seconds: int | None,
        strategy: ConflictStrategy,
    ) -> MemoryEntry:
        # Read current stored entry (if any)
        existing = await self._backend.get_entry(
            self.namespace_name, self.branch_name, key
        )

        # Increment our clock for this write
        new_clock = self._local_clock.increment(self.agent_id)

        if existing is None:
            # No conflict possible — first write to this key.
            # base_value is None for brand-new keys. [B1]
            entry = MemoryEntry(
                namespace=self.namespace_name,
                branch=self.branch_name,
                key=key,
                value=value,
                base_value=None,   # [B1] no ancestor yet
                agent_id=self.agent_id,
                clock=new_clock,
                tags=tags or [],
                ttl_seconds=ttl_seconds,
            )
        elif new_clock.concurrent_with(existing.clock):
            # Concurrent writes detected — resolve conflict
            log.warning(
                "conflict.detected",
                key=key,
                our_agent=self.agent_id,
                their_agent=existing.agent_id,
                strategy=strategy,
            )
            conflict = Conflict(
                namespace=self.namespace_name,
                branch=self.branch_name,
                key=key,
                entry_ours=MemoryEntry(
                    namespace=self.namespace_name,
                    branch=self.branch_name,
                    key=key,
                    value=value,
                    base_value=existing.base_value,  # [B1] carry through base
                    agent_id=self.agent_id,
                    clock=new_clock,
                ),
                entry_theirs=existing,
            )
            entry = await self._resolve_conflict(conflict, strategy, tags, ttl_seconds)
        else:
            # Causally ordered — safe update.
            # Store old value as base_value so future conflicts
            # have a real common ancestor. [B1]
            entry = MemoryEntry(
                namespace=self.namespace_name,
                branch=self.branch_name,
                key=key,
                value=value,
                base_value=existing.value,   # [B1] record ancestor
                agent_id=self.agent_id,
                clock=new_clock,
                tags=tags or [],
                ttl_seconds=ttl_seconds,
                updated_at=time.time(),
            )

        # [B8] Populate embedding if an embedding function was provided.
        if self._embedding_fn is not None:
            try:
                entry.embedding = await self._embedding_fn(entry.value)
            except Exception:
                log.warning("embedding.failed", key=key)

        await self._backend.save_entry(entry)
        self._local_clock = new_clock
        return entry

    # ── Conflict Resolution ────────────────────────────────────────────────────

    async def _resolve_conflict(
        self,
        conflict: Conflict,
        strategy: ConflictStrategy,
        tags: list[str] | None,
        ttl_seconds: int | None,
    ) -> MemoryEntry:
        if strategy == ConflictStrategy.RAISE:
            raise ConflictDetectedError(conflict)

        elif strategy == ConflictStrategy.LAST_WRITE_WINS:
            resolved_value = conflict.entry_ours.value
            log.info("conflict.resolved.last_write_wins", key=conflict.key)

        elif strategy == ConflictStrategy.FIRST_WRITE_WINS:
            resolved_value = conflict.entry_theirs.value
            log.info("conflict.resolved.first_write_wins", key=conflict.key)

        elif strategy == ConflictStrategy.MERGE_STRUCTURAL:
            resolved_value = await self._structural_merge(conflict)

        elif strategy == ConflictStrategy.MERGE_SEMANTIC:
            resolved_value = await self._semantic_merge(conflict)

        else:
            resolved_value = conflict.entry_ours.value

        merged_clock = conflict.entry_ours.clock.merge(conflict.entry_theirs.clock)
        return MemoryEntry(
            namespace=self.namespace_name,
            branch=self.branch_name,
            key=conflict.key,
            value=resolved_value,
            base_value=conflict.entry_theirs.value,  # [B1] resolved becomes new base
            agent_id=self.agent_id,
            clock=merged_clock,
            tags=tags or [],
            ttl_seconds=ttl_seconds,
            updated_at=time.time(),
        )

    async def _structural_merge(self, conflict: Conflict) -> Any:
        """
        Use the Rust three-way merge engine.
        Requires that values are dict-like (JSON objects).

        [B1] base_value is now read from the stored entry (the common
        ancestor saved at the time of the last successful write) rather
        than being hardcoded as {}.
        """
        ours_val = conflict.entry_ours.value
        theirs_val = conflict.entry_theirs.value

        # For non-dict values, fall back to last-write-wins
        if not isinstance(ours_val, dict) or not isinstance(theirs_val, dict):
            log.info("conflict.structural_merge.fallback_lww", key=conflict.key)
            return ours_val

        if not _RUST_AVAILABLE:
            # Rust extension not compiled — fall back to simple dict merge
            log.warning("conflict.rust_unavailable.fallback_dict_merge", key=conflict.key)
            return {**theirs_val, **ours_val}

        # [B1] Use the real common ancestor stored on the theirs entry.
        # Falls back to {} only for the very first write on a key.
        base_val = conflict.entry_theirs.base_value or {}

        result_json = py_three_way_merge(
            json.dumps(base_val),
            json.dumps(ours_val),
            json.dumps(theirs_val),
        )
        result = json.loads(result_json)

        if not result["is_clean"]:
            log.warning(
                "conflict.structural_merge.partial",
                key=conflict.key,
                unresolved_keys=result["conflict_keys"],
            )
        return result["merged"]

    async def _semantic_merge(self, conflict: Conflict) -> Any:
        """
        LLM-assisted merge for textual content.  [B11]
        Uses self._llm_merge_fn if provided; otherwise falls back to
        structural merge.
        """
        if self._llm_merge_fn is not None:
            from .protocol.semantic_merge import semantic_merge
            return await semantic_merge(
                key=conflict.key,
                value_ours=conflict.entry_ours.value,
                value_theirs=conflict.entry_theirs.value,
                agent_ours=conflict.entry_ours.agent_id,
                agent_theirs=conflict.entry_theirs.agent_id,
                llm_callable=self._llm_merge_fn,
            )
        log.info("semantic_merge.fallback_structural", key=conflict.key)
        return await self._structural_merge(conflict)

    # ── Branching API ──────────────────────────────────────────────────────────

    async def fork(self, branch_name: str) -> "AgentSkein":
        """
        Create a new branch from current branch.  [B2] [B3]
        Returns a new AgentSkein instance scoped to the new branch.

        [B3] Lazy copy-on-write: the Branch records its parent_branch.
        StorageBackend.get_entry() falls through to the parent branch on a
        miss so reads are O(1). Entries are only materialised to the child
        branch when written.  O(1) regardless of namespace size.
        """
        existing_branch = await self._backend.get_branch(
            self.namespace_name, branch_name
        )
        if existing_branch is None:
            new_branch = Branch(
                name=branch_name,
                namespace=self.namespace_name,
                parent_branch=self.branch_name,   # [B3] CoW pointer
                created_by=self.agent_id,
                head_clock=self._local_clock,
            )
            await self._backend.save_branch(self.namespace_name, new_branch)
            log.info(
                "branch.created",
                branch=branch_name,
                parent=self.branch_name,
                strategy="lazy_cow",
            )

        forked_mesh = AgentSkein(
            agent_id=self.agent_id,
            namespace=self.namespace_name,
            branch=branch_name,
            backend=self._backend,
            conflict_strategy=self._strategy,
            embedding_fn=self._embedding_fn,
            llm_merge_fn=self._llm_merge_fn,
        )
        forked_mesh._local_clock = self._local_clock
        return forked_mesh

    async def merge_to(
        self,
        target_branch: str = "main",
        strategy: ConflictStrategy | None = None,
    ) -> dict[str, Any]:
        """
        Merge all entries from self.branch_name into target_branch.
        Returns a summary: {merged_keys, conflict_keys, from_branch, to_branch}.

        Strategy semantics at merge time:
          * RAISE          → the first per-key conflict propagates a
                             ConflictDetectedError out of merge_to(). The
                             merge is abandoned, the source branch is NOT
                             marked merged, and the caller is responsible
                             for handling the conflict. This matches the
                             documented "conflict surfaces to the
                             application" contract.
          * Every other    → the resolver inside write() auto-resolves
            strategy         each conflict in place. conflict_keys in the
                             returned summary will normally be empty.
        """
        effective_strategy = strategy or self._strategy
        our_entries = await self._backend.get_branch_entries(
            self.namespace_name, self.branch_name
        )
        target_mesh = AgentSkein(
            agent_id=self.agent_id,
            namespace=self.namespace_name,
            branch=target_branch,
            backend=self._backend,
            conflict_strategy=effective_strategy,
            embedding_fn=self._embedding_fn,
            llm_merge_fn=self._llm_merge_fn,
        )
        merged_keys, conflict_keys = [], []
        for entry in our_entries:
            try:
                await target_mesh.write(
                    entry.key, entry.value,
                    tags=entry.tags,
                    ttl_seconds=entry.ttl_seconds,
                )
                merged_keys.append(entry.key)
            except ConflictDetectedError:
                # With RAISE the contract is "exception escapes" — propagate
                # so the caller can resolve manually. Do NOT mark the source
                # branch as merged; the merge has not happened.
                if effective_strategy == ConflictStrategy.RAISE:
                    log.warning(
                        "merge.conflict_raised",
                        key=entry.key,
                        from_branch=self.branch_name,
                        to_branch=target_branch,
                    )
                    raise
                # Defensive: any other strategy means the resolver handled
                # the conflict, so ConflictDetectedError shouldn't reach us.
                # If it does, surface the key in the summary instead of
                # silently dropping data.
                conflict_keys.append(entry.key)
                log.error("merge.conflict_unresolved", key=entry.key)

        # Mark branch as merged
        branch = await self._backend.get_branch(self.namespace_name, self.branch_name)
        if branch:
            branch.is_merged = True
            await self._backend.save_branch(self.namespace_name, branch)

        log.info(
            "branch.merged",
            from_branch=self.branch_name,
            to_branch=target_branch,
            merged=len(merged_keys),
            conflicts=len(conflict_keys),
        )
        return {
            "merged_keys": merged_keys,
            "conflict_keys": conflict_keys,
            "from_branch": self.branch_name,
            "to_branch": target_branch,
        }

    # ── Utilities ──────────────────────────────────────────────────────────────

    async def list_keys(self) -> list[str]:
        entries = await self._backend.get_branch_entries(
            self.namespace_name, self.branch_name
        )
        return [e.key for e in entries]

    async def snapshot(self) -> dict[str, Any]:
        """Return all key-value pairs in the current branch as a dict."""
        entries = await self._backend.get_branch_entries(
            self.namespace_name, self.branch_name
        )
        return {e.key: e.value for e in entries}

    async def delete(self, key: str) -> bool:
        """Delete a key from the current branch."""
        return await self._backend.delete_entry(
            self.namespace_name, self.branch_name, key
        )

    async def close(self) -> None:
        await self._backend.close()

    # ── Context manager support ────────────────────────────────────────────────

    async def __aenter__(self) -> "AgentSkein":
        await self.init()
        return self

    async def __aexit__(self, *args: Any) -> None:
        await self.close()
