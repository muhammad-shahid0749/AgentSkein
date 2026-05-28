"""
Semantic merge: when two agents write conflicting text values, ask an LLM
to produce a merged version that honours both contributions.

This is intentionally provider-agnostic — pass any callable that accepts
(prompt: str) → str. Works with Anthropic, OpenAI, Ollama, etc.
"""
from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any

LLMMergeCallable = Callable[[str], Awaitable[str]]


MERGE_PROMPT_TEMPLATE = """You are a careful editor helping merge two versions of a memory entry.

KEY: {key}

VERSION A (written by {agent_a}):
{value_a}

VERSION B (written by {agent_b}):
{value_b}

Task: Produce a single merged version that:
1. Preserves all unique information from both versions
2. Resolves contradictions by favouring the more specific or recent claim
3. Maintains factual accuracy
4. Is concise — do not add commentary or explanation

Output ONLY the merged content, nothing else."""


async def semantic_merge(
    key: str,
    value_ours: Any,
    value_theirs: Any,
    agent_ours: str,
    agent_theirs: str,
    llm_callable: LLMMergeCallable,
) -> Any:
    """
    Merge two conflicting values using an LLM.
    Returns the merged value (as string for text, original ours for non-text).
    """
    if not isinstance(value_ours, str) and not isinstance(value_theirs, str):
        # Not textual — return ours (structural merge handles dicts)
        return value_ours

    prompt = MERGE_PROMPT_TEMPLATE.format(
        key=key,
        agent_a=agent_ours,
        value_a=str(value_ours),
        agent_b=agent_theirs,
        value_b=str(value_theirs),
    )
    merged = await llm_callable(prompt)
    return merged.strip()
