"""
LangGraph example — multi-agent graph with AgentSkein checkpointing.

Requires:
    pip install 'agentskein[langgraph]'
    docker compose up redis -d

The graph has two nodes (researcher + writer) that share state via
AgentSkein. If interrupted and resumed, the checkpoint is persisted.
"""
from __future__ import annotations

import sys
import os

_project_root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if _project_root not in sys.path:
    sys.path.insert(0, _project_root)

import asyncio
from typing import TypedDict

try:
    from langgraph.graph import StateGraph, END
    from agentskein.adapters.langgraph_adapter import AgentSkeinCheckpointer
except ImportError:
    print("LangGraph not installed. Run: pip install 'agentskein[langgraph]'")
    exit(1)


class ResearchState(TypedDict):
    topic: str
    findings: list[str]
    draft: str


def research_node(state: ResearchState) -> ResearchState:
    """Simulated research agent."""
    findings = [
        f"Finding about {state['topic']}: CRDT clocks enable conflict-free merges.",
        f"Finding about {state['topic']}: Redis supports atomic Lua scripts for locking.",
    ]
    return {"findings": findings}


def write_node(state: ResearchState) -> ResearchState:
    """Simulated writer agent."""
    draft = f"# {state['topic']}\n\n" + "\n".join(f"- {f}" for f in state.get("findings", []))
    return {"draft": draft}


async def run():
    REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379/0")

    checkpointer = AgentSkeinCheckpointer(
        agent_id="orchestrator",
        namespace="langgraph-demo",
        redis_url=REDIS_URL,
    )

    graph = (
        StateGraph(ResearchState)
        .add_node("researcher", research_node)
        .add_node("writer", write_node)
        .add_edge("researcher", "writer")
        .add_edge("writer", END)
        .set_entry_point("researcher")
        .compile(checkpointer=checkpointer)
    )

    config = {"configurable": {"thread_id": "run-1"}}
    result = await graph.ainvoke(
        {"topic": "Multi-agent memory systems", "findings": [], "draft": ""},
        config=config,
    )
    print("Draft output:")
    print(result["draft"])


if __name__ == "__main__":
    asyncio.run(run())
