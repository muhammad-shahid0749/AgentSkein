"""
Run every documentation experiment in one go.

Output layout (under ${AGENTSKEIN_EXPERIMENT_RESULTS_DIR} —
default: ./experiment_results/):

    experiment_results/
    ├── run_summary.md            ← READ THIS FIRST
    ├── run_summary.json          ← machine-readable
    ├── <experiment_name>/
    │   ├── result.json           ← per-experiment outcome
    │   ├── stdout.txt            ← full captured stdout
    │   └── stderr.txt            ← full captured stderr
    └── _guide_server.log         ← FastAPI server log (when applicable)

Exit code: 0 if every experiment passed (skipped = neutral), 1 otherwise.

Run from the project root:
    python -m tests.experiments.run_all_experiments
or:
    python tests/experiments/run_all_experiments.py
"""
from __future__ import annotations

import os
import sys
import time
from pathlib import Path

# Allow running this file directly (without -m) by extending sys.path.
_REPO_ROOT = Path(__file__).resolve().parents[2]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from tests.experiments._experiment import write_run_summary           # noqa: E402
from tests.experiments import experiments_readme, experiments_guide   # noqa: E402


def main() -> int:
    rd = os.getenv(
        "AGENTSKEIN_EXPERIMENT_RESULTS_DIR",
        str(_REPO_ROOT / "experiment_results"),
    )
    Path(rd).mkdir(parents=True, exist_ok=True)

    t0 = time.time()
    print("=" * 70)
    print(f"  AgentSkein documentation experiments — results → {rd}")
    print("=" * 70)

    all_exps = []

    print("\n--- README.md experiments ---")
    all_exps.extend(experiments_readme.run_all(rd))

    print("\n--- AGENTS_INTEGRATION_GUIDE.md / docs/README.md experiments ---")
    all_exps.extend(experiments_guide.run_all(rd))

    results = [e.result for e in all_exps]
    write_run_summary(rd, results)

    passed = sum(1 for r in results if r.status == "pass")
    failed = sum(1 for r in results if r.status == "fail")
    skipped = sum(1 for r in results if r.status == "skipped")
    total_s = round(time.time() - t0, 2)

    print("\n" + "=" * 70)
    print(f"  {passed} PASS    {failed} FAIL    {skipped} SKIP    "
          f"({len(results)} total, {total_s}s)")
    print(f"  Summary: {rd}/run_summary.md")
    print("=" * 70)

    return 0 if failed == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
