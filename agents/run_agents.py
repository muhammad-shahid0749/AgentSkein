"""
Entry point — GitHub AI Ecosystem Intelligence Pipeline.

Prerequisites:
  Terminal 1:  python examples\\n8n_api_server\\server.py
  Terminal 2:  python agents\\run_agents.py

Output:  agents/ai_ecosystem_report.txt
"""
import sys, os
_project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _project_root not in sys.path:
    sys.path.insert(0, _project_root)

import asyncio
from agents.orchestrator_agent import OrchestratorAgent


async def main():
    orchestrator = OrchestratorAgent(
        agent_id  = "Orchestrator",
        namespace = "github-ai-ecosystem",
        base_url  = "http://localhost:8765",
    )
    await orchestrator.run()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\nShutdown.")
    except Exception as e:
        import traceback
        print(f"\nError: {e}")
        traceback.print_exc()
