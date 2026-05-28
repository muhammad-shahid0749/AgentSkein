"""
Scenario 2 — disjoint-key research pipeline
===========================================

Real-world claim under test:
    "Pattern A": when each agent writes to a UNIQUE top-level key, the
    3-way merge engine unions cleanly and every writer's contribution
    is preserved on main with full attribution.

How it runs:
    Three "researcher" agents look at the AI ecosystem from three angles:

      Researcher-1  POPULARITY   (ranks by GitHub stars)
      Researcher-2  ACTIVITY     (ranks by last-commit recency)
      Researcher-3  ADOPTION     (ranks by GitHub forks)

    Each forks its own branch, writes a finding to a DISJOINT top-level
    key, then merges to main. After all three merge, main must contain
    all three keys with attribution intact. This is the test that
    proves the "zero data loss across N concurrent writers" claim.

    No live GitHub API is required — the data is synthesised so the
    scenario runs deterministically inside a container.
"""
from __future__ import annotations

import asyncio
import os
from typing import Any

from agentskein import AgentSkein, ConflictStrategy
from agentskein.storage.memory_backend import InMemoryBackend

from tests.scenarios._recorder import ScenarioRecorder


# Synthetic findings — kept stable so the scenario produces reproducible runs.
FINDINGS = {
    "Researcher-1": {
        "metric":      "POPULARITY",
        "best_repo":   "Significant-Gravitas/AutoGPT",
        "score":       184213,
        "by_agent":    "Researcher-1",
        "recommendation": "AutoGPT leads by raw star count.",
    },
    "Researcher-2": {
        "metric":      "ACTIVITY",
        "best_repo":   "langgenius/dify",
        "score":       2026,
        "by_agent":    "Researcher-2",
        "recommendation": "Dify is the most actively maintained.",
    },
    "Researcher-3": {
        "metric":      "ADOPTION",
        "best_repo":   "langchain-ai/langchain",
        "score":       22580,
        "by_agent":    "Researcher-3",
        "recommendation": "LangChain has the deepest fork ecosystem.",
    },
}


async def run(results_dir: str) -> dict[str, Any]:
    description = (
        "Three researcher agents each write a finding to a unique top-level "
        "key (analysis-by-popularity / analysis-by-activity / "
        "analysis-by-adoption) on their own branch, then merge to main."
    )
    claim = (
        "Disjoint top-level keys are unioned cleanly by the 3-way merge "
        "engine; all 3 writers' contributions are preserved on main."
    )

    async with ScenarioRecorder(
        "scenario_02_disjoint_pipeline",
        results_dir=results_dir,
        description=description,
    ) as rec:
        backend = InMemoryBackend()

        async def researcher(name: str) -> None:
            mesh = AgentSkein(
                agent_id=name,
                namespace="ai-ecosystem",
                backend=backend,
                conflict_strategy=ConflictStrategy.MERGE_STRUCTURAL,
            )
            await mesh.init()
            branch = await mesh.fork(f"branch/{name}")
            metric = FINDINGS[name]["metric"].lower()
            key = f"analysis-by-{metric}"
            rec.event("researcher.write", agent=name, key=key)
            await branch.write(key, FINDINGS[name])
            summary = await branch.merge_to("main")
            rec.event(
                "researcher.merge",
                agent=name,
                merged_keys=summary.get("merged_keys"),
                conflict_keys=summary.get("conflict_keys"),
            )

        await asyncio.gather(*[researcher(n) for n in FINDINGS])

        # Verify on main
        coord = AgentSkein(agent_id="coord", namespace="ai-ecosystem", backend=backend)
        await coord.init()
        snap = await coord.snapshot()

        expected_keys = {
            "analysis-by-popularity",
            "analysis-by-activity",
            "analysis-by-adoption",
        }
        present = expected_keys & set(snap)
        missing = expected_keys - present

        attribution_ok = all(
            isinstance(snap.get(k), dict)
            and snap[k].get("by_agent") == FINDINGS[name]["by_agent"]
            for name, k in (
                ("Researcher-1", "analysis-by-popularity"),
                ("Researcher-2", "analysis-by-activity"),
                ("Researcher-3", "analysis-by-adoption"),
            )
        )

        rec.event(
            "verify.snapshot",
            present_keys=sorted(present),
            missing_keys=sorted(missing),
            attribution_ok=attribution_ok,
            total_keys=len(snap),
        )

        passed = (len(missing) == 0) and attribution_ok
        rec.set_outcome(
            passed=passed,
            claim=claim,
            summary=(
                f"All 3 disjoint keys present on main: "
                f"{sorted(present)}. Missing: {sorted(missing) or 'none'}. "
                f"Attribution intact: {attribution_ok}."
            ),
            metrics={
                "writers": len(FINDINGS),
                "perspectives_preserved": len(present),
                "perspectives_expected": len(expected_keys),
                "attribution_ok": attribution_ok,
                "total_keys_on_main": len(snap),
            },
        )

        return {
            "scenario": "scenario_02_disjoint_pipeline",
            "passed": passed,
            "claim": claim,
            "summary": f"{len(present)}/{len(expected_keys)} perspectives preserved on main.",
            "metrics": {
                "perspectives_preserved": len(present),
                "perspectives_expected": len(expected_keys),
                "attribution_ok": attribution_ok,
            },
        }


if __name__ == "__main__":
    import sys
    out = asyncio.run(run(os.getenv("AGENTSKEIN_RESULTS_DIR", "./test_results")))
    print(out)
    sys.exit(0 if out["passed"] else 1)
