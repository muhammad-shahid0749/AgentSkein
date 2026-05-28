"""
CrewAI adapter.

Replaces CrewAI's default short-term and long-term memory stores
with AgentSkein. Multiple crew members share a namespace; each agent
writes to its own branch and merges at defined checkpoints.

Usage:
    from agentskein.adapters.crewai_adapter import AgentSkeinStorage
    from crewai import Crew, Memory

    storage = AgentSkeinStorage(namespace="market-research-crew")
    crew = Crew(
        agents=[researcher, analyst, writer],
        memory=Memory(storage=storage),
    )
"""
from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any

from ..client import AgentSkein, ConflictStrategy


class AgentSkeinStorage:
    """
    Drop-in replacement for CrewAI's RAGStorage / SQLiteStorage.
    Provides the save() / search() / reset() interface CrewAI expects.
    """

    def __init__(
        self,
        namespace: str,
        redis_url: str = "redis://localhost:6379/0",
        conflict_strategy: ConflictStrategy = ConflictStrategy.MERGE_STRUCTURAL,
        embedding_fn: "Callable[[Any], Awaitable[list[float]]] | None" = None,
    ):
        self._namespace = namespace
        self._redis_url = redis_url
        self._strategy = conflict_strategy
        self._embedding_fn = embedding_fn
        self._meshes: dict[str, AgentSkein] = {}

    def _get_mesh(self, agent_id: str) -> AgentSkein:
        if agent_id not in self._meshes:
            self._meshes[agent_id] = AgentSkein(
                agent_id=agent_id,
                namespace=self._namespace,
                redis_url=self._redis_url,
                conflict_strategy=self._strategy,
                embedding_fn=self._embedding_fn,
            )
        return self._meshes[agent_id]

    async def save(self, agent_id: str, key: str, value: Any) -> None:
        mesh = self._get_mesh(agent_id)
        await mesh.init()
        await mesh.write(key, value)

    async def search(self, agent_id: str, query: str, limit: int = 5) -> list[dict]:
        """
        Search memory entries for a query string.
        If embedding_fn is set, uses cosine similarity on stored embeddings.
        Falls back to a substring match against both KEY and VALUE otherwise.

        The key-match path is what makes the integration-guide example
        `search("writer", "market", limit=5)` return entries whose KEY is
        "market-size" (CrewAI users commonly search by topic/key, not by the
        opaque JSON value).
        """
        mesh = self._get_mesh(agent_id)
        await mesh.init()

        if self._embedding_fn is not None:
            return await self._vector_search(mesh, query, limit)

        # Substring match against key OR value (case-insensitive).
        q = query.lower()
        snapshot = await mesh.snapshot()
        results = [
            {"key": k, "value": v}
            for k, v in snapshot.items()
            if q in k.lower() or q in str(v).lower()
        ]
        return results[:limit]

    async def _vector_search(
        self, mesh: AgentSkein, query: str, limit: int
    ) -> list[dict]:
        """Cosine similarity search over stored embeddings."""
        query_embedding = await self._embedding_fn(query)  # type: ignore[misc]
        entries = await mesh._backend.get_branch_entries(
            mesh.namespace_name, mesh.branch_name
        )

        scored = []
        for entry in entries:
            if entry.embedding is not None:
                score = _cosine_similarity(query_embedding, entry.embedding)
                scored.append((score, entry))

        scored.sort(key=lambda x: x[0], reverse=True)
        return [
            {"key": e.key, "value": e.value, "score": s}
            for s, e in scored[:limit]
        ]

    async def reset(self, agent_id: str) -> None:
        mesh = self._get_mesh(agent_id)
        keys = await mesh.list_keys()
        for key in keys:
            await mesh.delete(key)


def _cosine_similarity(a: list[float], b: list[float]) -> float:
    """Compute cosine similarity between two embedding vectors."""
    import math
    dot = sum(x * y for x, y in zip(a, b))
    norm_a = math.sqrt(sum(x * x for x in a))
    norm_b = math.sqrt(sum(x * x for x in b))
    if norm_a == 0 or norm_b == 0:
        return 0.0
    return dot / (norm_a * norm_b)
