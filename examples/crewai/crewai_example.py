"""
CrewAI example — shared memory across crew members via AgentSkein.

Requires:
    pip install 'agentskein[crewai]'
    docker compose up redis -d
"""
import sys
import os

_project_root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if _project_root not in sys.path:
    sys.path.insert(0, _project_root)

import asyncio
from agentskein.adapters.crewai_adapter import AgentSkeinStorage

REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379/0")


async def simulate_crew():
    storage = AgentSkeinStorage(namespace="market-research-crew", redis_url=REDIS_URL)

    # Researcher saves findings
    await storage.save("researcher", "market_size",
                       {"value": "$2B", "year": 2025, "source": "GartnerReport"})
    await storage.save("researcher", "key_players",
                       ["mem0", "Zep", "Redis Agent Memory"])
    await storage.save("researcher", "gap",
                       "No existing tool handles multi-writer conflict resolution")

    # Analyst saves its own findings
    await storage.save("analyst", "recommendation",
                       "Build AgentSkein to fill the multi-writer gap")
    await storage.save("analyst", "market_size",  # concurrent write!
                       {"value": "$2.3B", "year": 2025, "source": "IDCReport"})

    # Writer searches for context
    results = await storage.search("writer", "market_size", limit=3)
    print(f"Writer found {len(results)} results for 'market_size':")
    for r in results:
        print(f"  {r['key']}: {r['value']}")


if __name__ == "__main__":
    asyncio.run(simulate_crew())
