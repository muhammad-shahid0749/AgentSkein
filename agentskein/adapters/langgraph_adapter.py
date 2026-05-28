"""
LangGraph adapter.  [B5]

Replaces LangGraph's default in-memory checkpointer with AgentSkein,
giving multi-agent LangGraph graphs persistent, shared, conflict-aware memory.

Rewritten for LangGraph >= 0.2 BaseCheckpointSaver API.

Usage:
    from agentskein.adapters.langgraph_adapter import AgentSkeinCheckpointer
    from langgraph.graph import StateGraph

    checkpointer = AgentSkeinCheckpointer(
        agent_id="orchestrator",
        namespace="my-workflow",
    )
    graph = StateGraph(MyState).compile(checkpointer=checkpointer)
"""
from __future__ import annotations

from collections.abc import AsyncIterator, Iterator
from typing import Any

from ..client import AgentSkein, ConflictStrategy

try:
    from langgraph.checkpoint.base import (
        BaseCheckpointSaver,
        Checkpoint,
        CheckpointMetadata,
        CheckpointTuple,
    )
    from langchain_core.runnables import RunnableConfig
    _LANGGRAPH_AVAILABLE = True
except ImportError:
    _LANGGRAPH_AVAILABLE = False
    BaseCheckpointSaver = object   # type: ignore[assignment,misc]
    RunnableConfig = dict          # type: ignore[assignment,misc]


class AgentSkeinCheckpointer(BaseCheckpointSaver):  # type: ignore[misc]
    """
    A LangGraph-compatible checkpointer backed by AgentSkein.
    Extends BaseCheckpointSaver (langgraph >= 0.2).  [B5]
    """

    def __init__(
        self,
        agent_id: str,
        namespace: str,
        redis_url: str = "redis://localhost:6379/0",
        conflict_strategy: ConflictStrategy = ConflictStrategy.MERGE_STRUCTURAL,
    ):
        if not _LANGGRAPH_AVAILABLE:
            raise ImportError(
                "LangGraph is not installed. "
                "Install with: pip install 'agentskein[langgraph]'"
            )
        super().__init__()
        self._mesh = AgentSkein(
            agent_id=agent_id,
            namespace=namespace,
            redis_url=redis_url,
            conflict_strategy=conflict_strategy,
        )
        self._initialised = False

    async def _ensure_init(self) -> None:
        if not self._initialised:
            await self._mesh.init()
            self._initialised = True

    # ── Storage key helpers ────────────────────────────────────────────────────

    @staticmethod
    def _ckpt_key(config: RunnableConfig) -> str:
        cfg = config.get("configurable", {}) if isinstance(config, dict) else {}
        thread_id = cfg.get("thread_id", "default")
        checkpoint_ns = cfg.get("checkpoint_ns", "")
        return f"ckpt:{thread_id}:{checkpoint_ns}"

    # ── Async interface (preferred by LangGraph async graphs) ─────────────────

    async def aput(
        self,
        config: RunnableConfig,
        checkpoint: "Checkpoint",
        metadata: "CheckpointMetadata",
        new_versions: dict[str, Any],
    ) -> RunnableConfig:
        await self._ensure_init()
        key = self._ckpt_key(config)
        await self._mesh.write(key, {
            "checkpoint": checkpoint,
            "metadata": metadata,
            "new_versions": new_versions,
        })
        cfg = config.get("configurable", {}) if isinstance(config, dict) else {}
        return {
            **config,
            "configurable": {
                **cfg,
                "checkpoint_id": checkpoint["id"],
            },
        }

    async def aget_tuple(self, config: RunnableConfig) -> "CheckpointTuple | None":
        await self._ensure_init()
        key = self._ckpt_key(config)
        value = await self._mesh.read(key)
        if value is None:
            return None
        return CheckpointTuple(
            config=config,
            checkpoint=value["checkpoint"],
            metadata=value.get("metadata", {}),
            parent_config=None,
        )

    async def alist(
        self,
        config: RunnableConfig | None,
        *,
        filter: dict[str, Any] | None = None,  # noqa: A002  (LangGraph API parity)
        before: RunnableConfig | None = None,
        limit: int | None = None,
    ) -> AsyncIterator["CheckpointTuple"]:
        await self._ensure_init()
        keys = await self._mesh.list_keys()
        count = 0
        for key in keys:
            if limit is not None and count >= limit:
                break
            if key.startswith("ckpt:"):
                val = await self._mesh.read(key)
                if val:
                    count += 1
                    yield CheckpointTuple(
                        config=config or {},
                        checkpoint=val["checkpoint"],
                        metadata=val.get("metadata", {}),
                        parent_config=None,
                    )

    # ── Sync interface (required by BaseCheckpointSaver ABC) ──────────────────

    def get_tuple(self, config: RunnableConfig) -> "CheckpointTuple | None":
        import asyncio
        return asyncio.get_event_loop().run_until_complete(self.aget_tuple(config))

    def list(  # noqa: A003  (LangGraph API parity)
        self,
        config: RunnableConfig | None,
        *,
        filter: dict[str, Any] | None = None,  # noqa: A002  (LangGraph API parity)
        before: RunnableConfig | None = None,
        limit: int | None = None,
    ) -> Iterator["CheckpointTuple"]:
        import asyncio
        loop = asyncio.get_event_loop()

        async def _collect() -> list["CheckpointTuple"]:
            return [
                t async for t in self.alist(
                    config, filter=filter, before=before, limit=limit
                )
            ]

        return iter(loop.run_until_complete(_collect()))

    def put(
        self,
        config: RunnableConfig,
        checkpoint: "Checkpoint",
        metadata: "CheckpointMetadata",
        new_versions: dict[str, Any],
    ) -> RunnableConfig:
        import asyncio
        return asyncio.get_event_loop().run_until_complete(
            self.aput(config, checkpoint, metadata, new_versions)
        )
