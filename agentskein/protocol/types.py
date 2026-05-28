"""
AgentSkein core types.
All types use Pydantic v2 for runtime validation and JSON serialisation.
"""
from __future__ import annotations

import time
from enum import StrEnum  # stdlib since Python 3.11; pyproject pins >=3.12
from typing import Any
from uuid import uuid4

import ulid as _ulid_lib
from pydantic import BaseModel, Field, field_validator


class ConflictStrategy(StrEnum):
    """How to resolve a write conflict between two agents."""
    LAST_WRITE_WINS   = "last_write_wins"   # simplest, lossy
    FIRST_WRITE_WINS  = "first_write_wins"  # conservative
    MERGE_SEMANTIC    = "merge_semantic"    # LLM-assisted merge
    MERGE_STRUCTURAL  = "merge_structural"  # Rust three-way merge
    RAISE             = "raise"             # surface to application


class VectorClock(BaseModel):
    """
    Logical clock tracking causal order across agents.
    Each agent has a counter; we increment on every write.
    Used to detect concurrent writes (conflicts) vs causally-ordered writes.

    Example:
      Agent-A writes → clock becomes {"agent-A": 1}
      Agent-B reads then writes → clock becomes {"agent-A": 1, "agent-B": 1}
      Agent-C writes without reading → clock is {"agent-C": 1}
        → agent-C and agent-B are CONCURRENT → conflict!
    """
    clocks: dict[str, int] = Field(default_factory=dict)

    def increment(self, agent_id: str) -> "VectorClock":
        """Return a new VectorClock with agent_id incremented."""
        new_clocks = dict(self.clocks)
        new_clocks[agent_id] = new_clocks.get(agent_id, 0) + 1
        return VectorClock(clocks=new_clocks)

    def dominates(self, other: "VectorClock") -> bool:
        """Return True if self causally dominates other (self >= other everywhere)."""
        all_agents = set(self.clocks) | set(other.clocks)
        return all(
            self.clocks.get(a, 0) >= other.clocks.get(a, 0)
            for a in all_agents
        )

    def concurrent_with(self, other: "VectorClock") -> bool:
        """Return True if neither clock dominates the other (= conflict)."""
        return not self.dominates(other) and not other.dominates(self)

    def merge(self, other: "VectorClock") -> "VectorClock":
        """Component-wise maximum — used after conflict resolution."""
        all_agents = set(self.clocks) | set(other.clocks)
        return VectorClock(clocks={
            a: max(self.clocks.get(a, 0), other.clocks.get(a, 0))
            for a in all_agents
        })


class MemoryEntry(BaseModel):
    """
    The atomic unit of storage in AgentSkein.
    One entry = one piece of information an agent wants to remember.

    base_value stores the common ancestor at the moment this entry was last
    written (or forked). It is used by the three-way merge engine so it always
    has a real BASE rather than falling back to {}.  [B1]
    """
    id: str = Field(default_factory=lambda: str(_ulid_lib.new()))
    namespace: str                          # e.g. "task-123/research"
    branch: str = "main"                    # e.g. "main", "agent-B-fork"
    key: str                                # human-readable key
    value: Any                              # arbitrary JSON-serialisable content
    base_value: Any = None                  # [B1] common ancestor for 3-way merge
    embedding: list[float] | None = None    # semantic vector (set by embedding hook)
    agent_id: str                           # which agent wrote this
    clock: VectorClock = Field(default_factory=VectorClock)
    created_at: float = Field(default_factory=time.time)
    updated_at: float = Field(default_factory=time.time)
    ttl_seconds: int | None = None          # optional expiry
    tags: list[str] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)

    @field_validator("namespace")
    @classmethod
    def validate_namespace(cls, v: str) -> str:
        if not v or (v.startswith("/")):
            raise ValueError("Namespace must not start with /")
        return v.strip()


class Branch(BaseModel):
    """
    A named fork of a namespace's memory — like a Git branch.
    Agents can work in isolation on a branch then merge back to main.
    """
    id: str = Field(default_factory=lambda: str(uuid4()))
    name: str
    namespace: str
    parent_branch: str = "main"
    created_by: str   # agent_id that created this branch
    created_at: float = Field(default_factory=time.time)
    head_clock: VectorClock = Field(default_factory=VectorClock)
    is_merged: bool = False


class Conflict(BaseModel):
    """
    Represents a detected write conflict between two memory entries.
    Surfaced to the application when strategy=RAISE, or resolved internally.
    """
    id: str = Field(default_factory=lambda: str(uuid4()))
    namespace: str
    branch: str
    key: str
    entry_ours: MemoryEntry      # the entry we tried to write
    entry_theirs: MemoryEntry    # the conflicting entry already stored
    detected_at: float = Field(default_factory=time.time)
    resolution: "Resolution | None" = None


class Resolution(BaseModel):
    """The outcome of conflict resolution."""
    strategy_used: ConflictStrategy
    resolved_value: Any
    resolved_at: float = Field(default_factory=time.time)
    resolved_by: str   # "system" or agent_id if human-in-loop
