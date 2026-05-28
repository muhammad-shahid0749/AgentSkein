"""
Run every real-world scenario in sequence and write a top-level summary.

Outputs (relative to AGENTSKEIN_RESULTS_DIR, default ./test_results):
    run_summary.md          human/LLM digest spanning every scenario
    run_summary.json        same content, machine-readable
    <scenario>/events.jsonl per-scenario timeline (one event per line)
    <scenario>/result.json  per-scenario outcome
    <scenario>/summary.md   per-scenario summary

Exit code: 0 if every scenario passed, 1 otherwise.

Entry point used by docker-compose: `python tests/scenarios/run_all_scenarios.py`
"""
from __future__ import annotations

import asyncio
import os
import sys
import time
from pathlib import Path

# Make `tests.scenarios.*` importable when this file is run directly.
_ROOT = Path(__file__).resolve().parent.parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from tests.scenarios import (
    scenario_01_multi_writer_race,
    scenario_02_disjoint_pipeline,
    scenario_03_branch_merge_strategies,
    scenario_04_poisoning_defence,
)
from tests.scenarios._recorder import write_run_summary


SCENARIOS = [
    scenario_01_multi_writer_race,
    scenario_02_disjoint_pipeline,
    scenario_03_branch_merge_strategies,
    scenario_04_poisoning_defence,
]


async def main() -> int:
    results_dir = os.getenv("AGENTSKEIN_RESULTS_DIR", "./test_results")
    Path(results_dir).mkdir(parents=True, exist_ok=True)

    runs = []
    overall_start = time.time()
    for mod in SCENARIOS:
        scenario_name = mod.__name__.split(".")[-1]
        print(f"\n===> Running {scenario_name} ...")
        t0 = time.time()
        try:
            out = await mod.run(results_dir)
        except Exception as e:
            out = {
                "scenario": scenario_name,
                "passed": False,
                "claim": "(unhandled exception during run)",
                "summary": f"{type(e).__name__}: {e}",
                "metrics": {},
            }
        out["duration_s"] = round(time.time() - t0, 4)
        verdict = "PASS" if out["passed"] else "FAIL"
        print(f"     [{verdict}] {scenario_name} ({out['duration_s']:.2f}s)")
        if out.get("summary"):
            for line in str(out["summary"]).splitlines():
                print(f"        {line}")
        runs.append(out)

    write_run_summary(results_dir, runs)
    total = round(time.time() - overall_start, 4)
    passed = sum(1 for r in runs if r["passed"])
    print(
        f"\n=== {passed}/{len(runs)} scenarios passed ({total:.2f}s total) ===\n"
        f"Results: {results_dir}/run_summary.md"
    )
    return 0 if passed == len(runs) else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
