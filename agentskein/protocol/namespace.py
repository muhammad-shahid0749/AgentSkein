"""
A Namespace is a logical container that multiple agents share.
Think of it like a Git repository — it holds branches, each branch
holds memory entries, and agents can fork + merge.
"""
from __future__ import annotations

import time

from pydantic import BaseModel, Field

from .types import Branch, ConflictStrategy, VectorClock


class NamespaceConfig(BaseModel):
    """
    Configuration for a shared memory namespace.
    Set once at creation; agents operating within it inherit these rules.
    """
    name: str
    description: str = ""
    default_conflict_strategy: ConflictStrategy = ConflictStrategy.MERGE_STRUCTURAL
    max_branches: int = 50
    max_entries_per_branch: int = 10_000
    enable_poisoning_detection: bool = True
    poisoning_threshold: float = 0.85  # cosine similarity threshold
    enable_write_attribution: bool = True
    ttl_default_seconds: int | None = None
    created_at: float = Field(default_factory=time.time)
    created_by: str = "system"


class NamespaceState(BaseModel):
    """Runtime state of a namespace — stored in the backend."""
    config: NamespaceConfig
    branches: dict[str, Branch] = Field(default_factory=dict)
    global_clock: VectorClock = Field(default_factory=VectorClock)
    total_writes: int = 0
    total_conflicts_detected: int = 0
    total_conflicts_resolved: int = 0

    def get_branch(self, name: str = "main") -> Branch | None:
        return self.branches.get(name)

    def add_branch(self, branch: Branch) -> None:
        if len(self.branches) >= self.config.max_branches:
            raise ValueError(f"Namespace {self.config.name} has reached max branches")
        self.branches[branch.name] = branch
