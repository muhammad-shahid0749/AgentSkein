# Running the Documentation Experiments

This suite executes **every runnable command** quoted in `README.md` and
`AGENTS_INTEGRATION_GUIDE.md`, captures its output, and writes a structured
verdict to `./experiment_results/`. It is the answer to the question
*"do the things the docs tell users to run actually work?"* — no opinions,
just reproducible PASS / FAIL / SKIP per claim.

If something fails, you (or an LLM ingesting the JSON) can read the exact
stdout, stderr, exit code, and source-line range it came from.

---

## What the suite covers

### From `README.md`

| # | Experiment | README lines | What it checks |
|---|-----------|--------------|----------------|
| 1 | `readme_l9_license_file_present` | L9, L523 | A `LICENSE` file exists at repo root |
| 2 | `readme_l407_test_count_is_44` | L407 | `pytest tests/unit tests/e2e --collect-only` counts 44 tests |
| 3 | `readme_l122_quickstart_inline` | L122-L147 | Quickstart code runs inline |
| 4 | `readme_l150_quickstart_subprocess` | L149-L151 | `python quickstart.py` exits 0 |
| 5 | `readme_l260_backend_construction` | L260-L268 | `RedisBackend`, `SQLiteBackend`, `InMemoryBackend` all constructible |
| 6 | `readme_l282_langgraph_checkpointer` | L282-L292 | `AgentSkeinCheckpointer(...)` imports cleanly |
| 7 | `readme_l397_rust_extension_import` | L397 | `from agentskein._core import py_three_way_merge` (SKIP if Rust not built) |
| 8 | `readme_l406_pytest_unit_and_e2e` | L406 | `pytest tests/unit tests/e2e -v` |
| 9 | `readme_l411_pytest_integration` | L411 | `pytest tests/integration -v` (SKIP without Redis) |
| 10 | `readme_l414_cargo_test` | L414 | `cargo test --manifest-path core/Cargo.toml` (SKIP without cargo) |
| 11 | `readme_l346_comparison_run_all_benchmarks` | L346 | `python ../comparison/run_all_benchmarks.py` (this file is missing — should FAIL) |
| 12 | `readme_l422_project_layout_paths_exist` | L420-L447 | Every path in the project-layout block actually exists |
| 13 | `readme_l181_five_agent_pipeline` | L177-L208 | Boot API server, run `python agents/run_agents.py` |
| 14 | `readme_l184_ai_ecosystem_report_has_seven_sections` | L184-L194 | Resulting `ai_ecosystem_report.txt` contains 7 SECTION banners |

### From `AGENTS_INTEGRATION_GUIDE.md` and `docs/README.md`

| # | Experiment | Guide lines | What it checks |
|---|-----------|-------------|----------------|
| 15 | `guide_l502_crewai_storage_direct` | L501-L518 | `AgentSkeinStorage.save / search` direct usage |
| 16 | `guide_l551_autogen_remember_recall` | L551-L576 | `AgentSkeinStore.remember / recall` round-trip |
| 17 | `docs_readme_autogen_put_get_broken` | docs/README.md L110-L118 | `store.put / store.get` (**known broken — should FAIL**) |
| 18 | `guide_l432_langgraph_checkpointer_construct` | L425-L457 | `AgentSkeinCheckpointer(...)` (SKIP if langgraph not installed) |
| 19 | `examples_raw_api_multi_agent_demo` | (README L431) | `python examples/raw_api/multi_agent_demo.py` |
| 20 | `guide_l401_get_health` | L401 | `GET /health` |
| 21 | `guide_l242_post_init_namespace` | L240-L249 | `POST /namespace/{ns}/init` |
| 22 | `guide_l319_write_then_read` | L319-L327, L356-L371 | Write a key, read it back |
| 23 | `guide_l268_fork_and_merge` | L266-L347 | Fork branch, write to it, merge to main, read on main |
| 24 | `guide_l357_get_snapshot` | L357-L371 | `GET /snapshot` returns the dict |
| 25 | `guide_l299_detect_poisoning` | L296-L311 | Adversarial flagged, benign passes |
| 26 | `guide_branches_list` | L398 | `GET /namespace/{ns}/branches` lists `main` |

Total: 26 experiments.

---

## How to run

### Path A — inside the Docker compose stack (recommended, no local Python setup)

```powershell
# Windows
docker compose up redis api -d
docker compose run --rm test-runner python tests/experiments/run_all_experiments.py
notepad .\experiment_results\run_summary.md
```

```bash
# Ubuntu
docker compose up redis api -d
docker compose run --rm test-runner python tests/experiments/run_all_experiments.py
less ./experiment_results/run_summary.md
```

### Path B — native Python (after `rename_to_agentskein.ps1` / `.sh`)

```powershell
# Windows
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -e ".[dev]"
pip install maturin && maturin develop      # optional, for the Rust extension
docker compose up redis -d                  # optional, for the integration tests
python tests/experiments/run_all_experiments.py
notepad .\experiment_results\run_summary.md
```

```bash
# Ubuntu
python3.12 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
pip install maturin && maturin develop
docker compose up redis -d
python tests/experiments/run_all_experiments.py
less ./experiment_results/run_summary.md
```

The runner emits one folder per experiment under `experiment_results/`:

```
experiment_results/
├── run_summary.md                          ← top-level digest
├── run_summary.json                        ← same content, JSON
├── readme_l122_quickstart_inline/
│   ├── result.json                         ← outcome + metrics
│   ├── stdout.txt                          ← full captured stdout
│   └── stderr.txt                          ← full captured stderr
├── readme_l181_five_agent_pipeline/
│   └── ...
├── guide_l299_detect_poisoning/
│   └── ...
└── _guide_server.log                       ← FastAPI server log
```

### Run just one experiment file

```bash
python -m tests.experiments.experiments_readme       # just README experiments
python -m tests.experiments.experiments_guide        # just guide / docs experiments
```

---

## How to read the output

Open `experiment_results/run_summary.md`. The header shows the PASS / FAIL /
SKIP counts. The table below lists every experiment with:

- the source document and line range,
- verdict,
- duration,
- a one-line note (skip reason or failure message).

Then for each experiment there is a detail block with the exact command, exit
code, last 15 lines of stdout, and last 15 lines of stderr. For an LLM ingesting
the JSON, `experiment_results/run_summary.json` contains the same content
without prose.

### Expected verdicts on a clean install today

These reflect known issues already documented in `DOCS_VERIFICATION_REPORT.md`:

| Experiment | Expected verdict | Why |
|------------|------------------|-----|
| `readme_l9_license_file_present` | **FAIL** | No `LICENSE` file at repo root — known gap. |
| `readme_l346_comparison_run_all_benchmarks` | **FAIL** | `comparison/run_all_benchmarks.py` does not exist in the repo. |
| `docs_readme_autogen_put_get_broken` | **FAIL** | The docs/README.md AutoGen snippet calls `.put` / `.get`, which don't exist on `AgentSkeinStore`. Capturing the failure is the point. |
| `readme_l397_rust_extension_import` | SKIP unless Rust built | Run `maturin develop` to flip this to PASS. |
| `readme_l411_pytest_integration` | SKIP unless Redis up | `docker compose up redis -d` |
| `readme_l414_cargo_test` | SKIP unless cargo on PATH | Install Rust via rustup |
| `guide_l432_langgraph_checkpointer_construct` | SKIP unless langgraph installed | `pip install "agentskein[langgraph]"` |
| Everything else | **PASS** | If anything else fails, the docs are out of sync with the code. |

---

## When to re-run

- After every documentation change (README, AGENTS_INTEGRATION_GUIDE, docs/).
- After every adapter or example change.
- Before tagging a public release.

The suite is fast — under a minute on a laptop without Rust, around 2 minutes
with the cargo and pytest steps included.

---

## Adding a new experiment

1. Open `tests/experiments/experiments_readme.py` (or `experiments_guide.py`).
2. Write a function like:
   ```python
   def run_my_new_check(results_dir):
       exp = Experiment(
           "readme_lXYZ_my_new_check",
           source_doc="README.md",
           source_lines="L420-L425",
           claim="what the docs promise",
           command="how a user would run it",
           results_dir=results_dir,
       )
       with exp:
           exp.run_callable(my_inline_check_fn)
           # or: exp.run_subprocess([sys.executable, "my_script.py"], cwd=...)
       return exp
   ```
3. Append it to `run_all(...)` in the same file.
4. Re-run. The new experiment appears in `run_summary.md` automatically.
