# Running the AgentSkein Real-World Tests

This document is for **Muhammad** (or any new contributor) to run the
four real-world test scenarios that prove AgentSkein addresses the
multi-writer problem in LLM agent memory.

There are two ways to run the suite — pick whichever matches the box
you are sitting at right now. Both write the same results to the same
folder (`./test_results/`), in the same format, so an LLM can ingest
them either way.

---

## What the suite tests

| Scenario | Claim under test | Pass condition |
|----------|------------------|----------------|
| `scenario_01_multi_writer_race` | AgentSkein detects 5 concurrent writers; plain dict and naive Redis silently lose 4 of 5. | All 5 writers visible as disjoint keys in AgentSkein; vector-clock conflict on the shared key is detected. |
| `scenario_02_disjoint_pipeline` | "Pattern A": 3 researchers writing unique top-level keys are unioned cleanly on `main` with full attribution. | 3/3 keys present on `main`, `by_agent` attribution intact. |
| `scenario_03_branch_merge_strategies` | All 5 conflict strategies (`LAST_WRITE_WINS`, `FIRST_WRITE_WINS`, `MERGE_STRUCTURAL`, `MERGE_SEMANTIC`, `RAISE`) produce the documented outcome. | Each strategy's final state matches its spec; `RAISE` raises `ConflictDetectedError`. |
| `scenario_04_poisoning_defence` | `PoisoningDetector` blocks 6 injection payloads, flags none of 3 benign writes, and raises a medium alert on an overwrite storm. | All 6 injections blocked, 0 false positives, ≥1 storm alert. |

---

## Result format (same on both OSes)

After a run, `./test_results/` looks like this:

```
test_results/
├── run_summary.md                          ← read this first
├── run_summary.json                        ← machine-readable digest
├── scenario_01_multi_writer_race/
│   ├── events.jsonl                        ← one JSON object per event
│   ├── result.json                         ← outcome + metrics
│   └── summary.md                          ← per-scenario human/LLM readable
├── scenario_02_disjoint_pipeline/
│   ├── events.jsonl
│   ├── result.json
│   └── summary.md
├── scenario_03_branch_merge_strategies/
│   └── ...
└── scenario_04_poisoning_defence/
    └── ...
```

The JSONL files are designed for LLM ingestion: every line is a
self-describing event of the form
`{"ts": 0.123, "event": "agentskein.merge", "agent": "agent-3", ...}`.

---

## Path A — Docker (recommended; identical on Windows and Ubuntu)

**Prerequisites:** Docker Desktop (Windows) or `docker` + `docker compose`
plugin (Ubuntu 22.04+).

### Windows (PowerShell)

```powershell
# 1. From the project root, rename the package directory once
.\rename_to_agentskein.ps1

# 2. Build and start Redis + API
docker compose up redis api -d

# 3. Run the test-runner (writes JSONL + Markdown to .\test_results\)
docker compose run --rm test-runner

# 4. Read the summary
notepad .\test_results\run_summary.md

# 5. Stop the stack
docker compose down
```

### Ubuntu (bash)

```bash
# 1. From the project root, rename the package directory once
bash rename_to_agentskein.sh

# 2. Build and start Redis + API
docker compose up redis api -d

# 3. Run the test-runner (writes JSONL + Markdown to ./test_results/)
docker compose run --rm test-runner

# 4. Read the summary
less ./test_results/run_summary.md

# 5. Stop the stack
docker compose down
```

If you want to re-run just one scenario inside the container:

```bash
docker compose run --rm test-runner \
    python tests/scenarios/scenario_01_multi_writer_race.py
```

---

## Path B — Native Python (no Docker)

Use this if you want to attach a debugger or iterate on a single
scenario quickly.

### Windows (PowerShell)

```powershell
# 1. Rename the package directory (only the first time)
.\rename_to_agentskein.ps1

# 2. Create and activate a fresh venv
python -m venv .venv
.\.venv\Scripts\Activate.ps1

# 3. Install AgentSkein (editable) and test deps
pip install -e ".[dev]"

# 4. (Optional) compile the Rust merge engine for full-speed merges
pip install maturin
maturin develop

# 5. (Optional) start Redis so scenario_01 can compare against naive Redis
docker compose up redis -d

# 6. Run the suite
$env:AGENTSKEIN_RESULTS_DIR = ".\test_results"
python tests\scenarios\run_all_scenarios.py

# 7. Read the summary
notepad .\test_results\run_summary.md
```

### Ubuntu (bash)

```bash
# 1. Rename the package directory (only the first time)
bash rename_to_agentskein.sh

# 2. Create and activate a fresh venv
python3.12 -m venv .venv
source .venv/bin/activate

# 3. Install AgentSkein (editable) and test deps
pip install -e ".[dev]"

# 4. (Optional) compile the Rust merge engine for full-speed merges
pip install maturin
maturin develop

# 5. (Optional) start Redis so scenario_01 can compare against naive Redis
docker compose up redis -d

# 6. Run the suite
export AGENTSKEIN_RESULTS_DIR=./test_results
python tests/scenarios/run_all_scenarios.py

# 7. Read the summary
less ./test_results/run_summary.md
```

---

## Reading the JSONL events with an LLM

Each `events.jsonl` is one event per line. To feed an LLM, you can do:

```bash
# Feed the timeline of a single scenario to your LLM of choice
cat test_results/scenario_01_multi_writer_race/events.jsonl
```

Every event has the shape:

```json
{"ts": 0.1842, "event": "agentskein.merge", "agent": "agent-3",
 "merged_keys": ["market-size", "by-agent-3"], "conflict_keys": []}
```

The `ts` field is seconds since the scenario started. The `event` field
is the symbolic event name. All other fields are scenario-specific
payload — included so an LLM can reconstruct exactly what happened
without needing the source code.

---

## Troubleshooting

| Symptom | Likely cause | Fix |
|---------|--------------|-----|
| `ModuleNotFoundError: No module named 'agentskein'` | Directory rename hasn't run | Run `.\rename_to_agentskein.ps1` (Windows) or `bash rename_to_agentskein.sh` (Ubuntu) |
| `scenario_01` Naive-Redis line says "skipped" | Redis not reachable | `docker compose up redis -d` |
| Docker build fails on `maturin build` | Rust toolchain too old in cache | `docker compose build --no-cache api` |
| Results directory is empty on Windows | Bind-mount path issue | Make sure you run `docker compose run` from the project root, not from inside a subdirectory |
| `agentskein/` already exists, rename script skips | You already ran the rename — that's fine | Carry on; the script is idempotent |
