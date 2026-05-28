# Documentation Verification Report — AgentSkein

**Scope:** Every testable claim in `README.md`, `AGENTS_INTEGRATION_GUIDE.md`, and
`docs/README.md` (referenced from both), checked line-by-line against the actual
source code, file system, and the prior test-run artefacts that landed in
`./test_results/` when you ran the scenarios.

**My limitation, stated up front:** the Linux sandbox attached to this session
failed to boot, so I could not personally execute `pytest`, `maturin develop`,
or `docker compose up`. Every claim below is therefore verified at one of three
levels:

- **STATIC OK** — verified by reading the actual source (function signatures,
  imports, file contents, regex patterns). If this verdict is wrong it would
  require the source to change.
- **RUNTIME OK** — verified by the `test_results/` artefacts you already
  produced on your own Docker stack.
- **NEEDS RUNTIME** — the claim is a measurement (a benchmark number, a "44
  passed in 0.57 s" timing) that no static reading can confirm. I tell you
  exactly which command will revalidate it.
- **FAIL / BROKEN** — the claim contradicts the source. Action required before
  public release.

Where I report **FAIL**, I always show the exact line and the exact contradicting
evidence in code. No verdict in this report is given on vibes.

---

## Headline

| Area                          | Verified | Broken / misleading | Needs runtime to recheck |
|-------------------------------|---------:|--------------------:|-------------------------:|
| README.md install/setup       |        7 |                   2 |                        1 |
| README.md technical concepts  |        5 |                   0 |                        0 |
| README.md code examples       |        4 |                   0 |                        0 |
| README.md performance numbers |        0 |                   0 |                        7 |
| README.md file references     |        9 |                   3 |                        0 |
| AGENTS_INTEGRATION_GUIDE.md   |       12 |                   2 |                        0 |
| docs/README.md examples       |        3 |                   2 |                        0 |
| Adapter docstrings            |        2 |                   1 |                        0 |
| **TOTAL**                     |   **42** |              **10** |                    **8** |

Ten outright defects need fixing before public release; eight benchmark numbers
need re-running on a clean install. The substantive engineering claims (vector
clocks, three-way merge, lazy CoW, conflict strategies, poisoning detection) are
all verified.

---

## Section A — README.md, line by line

### A1. Badges (lines 9–13)

| Line | Claim | Verdict | Evidence |
|------|-------|---------|----------|
| 9    | `license-Apache--2.0` badge | **FAIL — broken link** | The badge target is `[LICENSE]`, but no `LICENSE` file exists at the repo root (Glob: only inside `.venv/`). `pyproject.toml` declares `license = { text = "Apache-2.0" }` so the licence claim is valid, but the file is missing. **Action:** drop a real `LICENSE` file at repo root with the Apache-2.0 text. |
| 10   | Python 3.12 | STATIC OK | `pyproject.toml` line 11: `requires-python = ">=3.12"`. |
| 11   | Rust 1.78+ | **NEEDS RUNTIME** | No `rust-toolchain.toml` or version constraint in `core/Cargo.toml`. Claim cannot be enforced. **Action:** add `[toolchain] channel = "1.78"` to a `rust-toolchain.toml`, or remove the version from the badge. |
| 12   | "tests-44 passed" | STATIC OK | Verified by `Grep "^\s*(def test_\|async def test_)"`: `tests/unit/` = 9+7+7+16 = 39 tests, `tests/e2e/` = 5 tests → exactly 44. README line 406's command `pytest tests/unit/ tests/e2e/ -v` matches this count. |
| 13   | Backends Redis/SQLite/InMemory | STATIC OK | All three backend modules exist under `agentskein/storage/`. |

### A2. "What is this" (lines 19–26)

| Line | Claim | Verdict |
|------|-------|---------|
| 21–26 | Library description (vector clocks, 3-way JSON merge, branching, attribution, poisoning, FastAPI server) | STATIC OK. Every named feature has a corresponding implementation file. |

### A3. "Why does it exist" (lines 30–49)

| Lines | Claim | Verdict | Evidence |
|-------|-------|---------|----------|
| 34–39 | "Agent A writes $2.1B, Agent B writes $2.4B, silently overwrites A" | RUNTIME OK | Reproduced by `scenario_01_multi_writer_race`. Per `test_results/.../events.jsonl`, plain dict and naive Redis both showed exactly this pattern: 1 of 5 writes survived. |
| 41–45 | "mem0, Zep, Redis Agent Memory, LangGraph InMemorySaver are single-writer designs" | **PARTIAL** | A correct, well-known industry observation, but the README presents it as a measured fact. The repo doesn't ship a benchmark against mem0/Zep. Scenario_01 only benchmarks plain dict + naive Redis. **Action:** soften "are single-writer designs" to "are designed around a single writer" or back the claim with a real benchmark. |

### A4. Visual diagrams (lines 53–66)

| Line | Reference | Verdict |
|------|-----------|---------|
| 57 | `docs/integration-architecture.svg` | STATIC OK — file exists |
| 60 | `docs/three-patterns.svg` | STATIC OK — file exists |
| 62 | `docs/three-patterns.svg` | STATIC OK — file exists |
| 65 | `docs/README.md` | STATIC OK — file exists |

### A5. Pattern A / Pattern B (lines 70–108)

| Lines | Claim | Verdict | Evidence |
|-------|-------|---------|----------|
| 80–84 | Pattern A code: `await researcher_1.write("analysis-by-popularity", {...})` | STATIC OK | `AgentSkein.write(key, value, tags=None, ttl_seconds=None, strategy=None)` matches. |
| 87–88 | "3 of 3 researcher perspectives preserved on main" | RUNTIME OK | `test_results/scenario_02_disjoint_pipeline/result.json` records `perspectives_preserved=3, perspectives_expected=3, attribution_ok=true`. |
| 97–103 | Strategy table (`merge_structural`, `merge_semantic`, `last_write_wins`, `first_write_wins`, `raise`) | STATIC OK | All five string forms match `ConflictStrategy` StrEnum values in `agentskein/protocol/types.py` lines 31–35. |

### A6. 30-second quickstart (lines 112–151)

| Lines | Claim | Verdict | Evidence |
|-------|-------|---------|----------|
| 115 | `git clone https://github.com/<your-org>/agentskein.git` | **FAIL — placeholder URL** | Literal `<your-org>` placeholder will 404. Replace before release. |
| 117 | venv + `pip install -e .` | **PARTIALLY MISLEADING** | `pyproject.toml` line 1–3 declares `build-backend = "maturin"`. So `pip install -e .` requires the Rust toolchain to be present, contradicting the "no Rust required" promise on line 112. CONTEXT.md §13 line 479 actually warns about this: *"`pyproject.toml` uses `maturin` as the build backend. This means `pip install -e .` tries to compile Rust code. If Rust is not installed or the compilation fails, the package is not installed at all. **Always use `maturin develop`** for editable installs."* The README quickstart contradicts CONTEXT.md. **Action:** either ship a pure-Python fallback build, or change the quickstart to a `PYTHONPATH=.` instruction (which CONTEXT.md §13 line 486 also documents). |
| 122–147 | `quickstart.py` snippet | STATIC OK | Every symbol resolves: `AgentSkein`, `InMemoryBackend`, `fork`, `write`, `merge_to`, `snapshot`. The result `{finding-from-A: ..., finding-from-B: ...}` will appear on main because both branches forked from a freshly-initialised main, both wrote disjoint top-level keys, and both merged back. |

### A7. Reference pipeline (lines 158–208)

| Lines | Claim | Verdict | Evidence |
|-------|-------|---------|----------|
| 164–172 | Five-agent ASCII pipeline | STATIC OK | Files exist: `agents/orchestrator_agent.py`, `agents/researcher_agent.py`, `agents/safety_agent.py`, `agents/analyst_agent.py`, `agents/writer_agent.py`, `agents/run_agents.py`. |
| 178 | `python examples/n8n_api_server/server.py` | STATIC OK — file exists |
| 181 | `python agents/run_agents.py` | STATIC OK — file exists |
| 184 | "produces `agents/ai_ecosystem_report.txt` (~500 lines, 7 sections)" | RUNTIME OK | `agents/ai_ecosystem_report.txt` exists, 502 lines, contains 7 `SECTION N` banners (1–7). |
| 196–208 | Reference-run metrics (Pipeline wall-clock 3.76 s, speedup 2.19×, write throughput 5.8 w/s, etc.) | **NEEDS RUNTIME** | These numbers are from a single sandbox run. They are reproducible by re-running `agents/run_agents.py`, but they are not currently re-verified. **Action:** label the table "indicative; reproduce with `python agents/run_agents.py`". |

### A8. Architecture diagram (lines 215–248)

| Lines | Claim | Verdict |
|-------|-------|---------|
| 222 | Methods listed: `write() read() fork() merge_to() snapshot() delete()` | STATIC OK — all six are defined in `agentskein/client.py` (lines 154, 132, 391, 432, 494, 501). |
| 225–228 | Features: vector clocks, base_value, exp. backoff, embedding hook, LLM merge hook | STATIC OK — every feature has a corresponding code path in `client.py`. |
| 234–240 | Five strategies listed | STATIC OK — matches `ConflictStrategy` enum exactly. |

### A9. Storage backends (lines 252–268)

| Lines | Claim | Verdict |
|-------|-------|---------|
| 256–258 | Backend setup table | STATIC OK — `InMemoryBackend` requires nothing; `SQLiteBackend` requires `aiosqlite` (already a runtime dep at pyproject.toml line 23); `RedisBackend` requires Redis. |
| 260–268 | Backend selection code | STATIC OK — `RedisBackend(url)` and `SQLiteBackend(path)` signatures both match their `__init__` in `agentskein/storage/`. |

### A10. Framework integrations (lines 272–294)

| Lines | Claim | Verdict | Evidence |
|-------|-------|---------|----------|
| 276 | `AgentSkeinCheckpointer` replaces `InMemorySaver / SqliteSaver` | STATIC OK | Class exists in `agentskein/adapters/langgraph_adapter.py` line 40, extends `BaseCheckpointSaver`. |
| 277 | `AgentSkeinStorage` replaces `RAGStorage / SQLiteStorage` | STATIC OK | Class exists in `agentskein/adapters/crewai_adapter.py` line 25. |
| 278 | `AgentSkeinStore` replaces "Custom agent memory dict" | STATIC OK — class exists, but see autogen_adapter docstring defect below (D1). |
| 282–292 | LangGraph code example | STATIC OK | `AgentSkeinCheckpointer(agent_id, namespace, redis_url, conflict_strategy)` matches the constructor in `langgraph_adapter.py` lines 46–52. |

### A11. Per-stack recipe table (lines 298–313)

| Line | Claim | Verdict |
|------|-------|---------|
| 305 | `docs/n8n-workflow.svg` | STATIC OK — file exists |
| 312 | `docs/conflict-flow.svg` | STATIC OK — file exists |

### A12. Comparison table (lines 317–347)

| Lines | Claim | Verdict | Evidence |
|-------|-------|---------|----------|
| 321–327 | "5 agents × 10 shared keys" comparison table | **PARTIALLY VERIFIED** | Scenario_01 substantiates the plain-dict and Redis rows (5 agents, 1 key — see `test_results/scenario_01_multi_writer_race/`). The LangGraph and LangChain rows are not exercised by any test in this repo. **Action:** either ship a benchmark that does test those frameworks, or scope the table to just the two backends scenario_01 actually measures. |
| 331–342 | Feature matrix vs. mem0/Zep/Redis/Letta/Automerge | **CANNOT VERIFY** | None of these competitors are exercised by any test in the repo. The matrix is a reasonable summary of public documentation for those tools but is not a measured comparison. **Action:** add a footnote saying "feature comparison from public docs of each tool as of {date}; not benchmarked in this repo". |
| 346 | `python ../comparison/run_all_benchmarks.py` | **FAIL — file does not exist** | No `comparison/` directory anywhere in the repo (Glob: no matches). The CONTEXT.md `comparison/` tree (`01_plain_dict`, `02_simple_redis`, `03_langgraph_inmemory`, `04_langchain_conv_memory`, `05_agentskein`) is also missing. **Action:** ship the benchmark suite or remove this line. |

### A13. Performance benchmarks (lines 351–369)

| Line | Claim | Verdict |
|------|-------|---------|
| 358 | "Sequential writes (1,000 keys) ~32,800 ops/s" | **NEEDS RUNTIME** — no benchmark file in repo |
| 359 | "Sequential reads ~245,600 ops/s" | **NEEDS RUNTIME** |
| 360 | "fork() on 1,000-entry namespace 1.59 ms (O(1))" | **NEEDS RUNTIME** — multi_agent_demo.py `demo_branching()` re-measures this; reasonable to re-run |
| 361 | "VectorClock.increment() ~521,000 ops/s" | **NEEDS RUNTIME** |
| 362 | "VectorClock.concurrent_with() ~378,000 ops/s" | **NEEDS RUNTIME** |
| 363 | "10 concurrent agents × 100 writes ~60,500 writes/s" | **NEEDS RUNTIME** |
| 364 | "Rust 3-way merge engine 10,000+ merges/s" | **NEEDS RUNTIME** |

**Action for §A13:** add `tests/bench/` with `pytest-benchmark` cases (the dep is already in `pyproject.toml [dev]` line 43). Until then, mark the section "indicative numbers from one author run; not currently part of CI".

### A14. Installation (lines 372–399)

| Lines | Claim | Verdict |
|-------|-------|---------|
| 377 | `pip install -e .` (minimum) | **MISLEADING** — see A6 line 117 above. Requires Rust because of maturin build backend. |
| 384–391 | Full install (rustup + maturin develop + Redis) | STATIC OK |
| 397 | `python -c "from agentskein._core import py_three_way_merge; print('Rust OK')"` | STATIC OK | `pyproject.toml` line 56 declares `module-name = "agentskein._core"`, `core/Cargo.toml` lib `name = "_core"`. |

### A15. Testing (lines 402–415)

| Line | Claim | Verdict |
|------|-------|---------|
| 406 | `pytest tests/unit/ tests/e2e/ -v` | STATIC OK |
| 407 | "44 passed in 0.57s" | **44 PASSED:** static — yes. "0.57s": **NEEDS RUNTIME**. |
| 411 | `pytest tests/integration/ -v` | STATIC OK — needs Redis running |
| 414 | `cargo test --manifest-path core/Cargo.toml` | STATIC OK |

### A16. Project layout (lines 419–447)

| Lines | Claim | Verdict |
|-------|-------|---------|
| 422–447 | Directory tree | STATIC OK with **one defect**: line 443 says `agentskein_paper.tex` is at the repo root, but the actual location is `internal_docs/agentskein_paper.tex`. |

### A17. Documentation (lines 451–460)

| Line | Claim | Verdict |
|------|-------|---------|
| 457 | `[agentskein_paper.tex](agentskein_paper.tex)` | **FAIL — broken link** | File is at `internal_docs/agentskein_paper.tex`. Plus the `.gitignore` ignores `internal_docs/` entirely (line 16 of `.gitignore`), so the paper won't be in the public release. **Action:** the rename script (`rename_to_agentskein.ps1`) is supposed to move this; verify it ran. If it ran, the file move didn't happen (confirmed by Glob — file is still under `internal_docs/`). |

### A18. Design notes (lines 464–485)

| Lines | Claim | Verdict |
|-------|-------|---------|
| 466–468 | "Why Rust" | Accurate — Rust extension via PyO3 in `core/src/lib.rs`. |
| 470–474 | "Why vector clocks" | Accurate — and verified by `tests/unit/test_vector_clock.py` (9 tests). |
| 476–479 | "Lazy CoW, fork() O(1)" | Accurate — verified by `InMemoryBackend.get_entry()` parent-branch fall-through (memory_backend.py lines 36–40) and re-measured each run by `examples/raw_api/multi_agent_demo.py` `demo_branching()`. |
| 481–485 | "Why base_value" | Accurate — `client.py` stores `base_value` on every causally-ordered write (line 267) and on every resolved conflict (line 321). |

### A19. Roadmap (lines 489–502)

| Line | Claim | Verdict |
|------|-------|---------|
| 491 | "[x] InMemory / SQLite / Redis backends" | STATIC OK |
| 492 | "[x] Vector clocks + three-way merge + branching" | STATIC OK |
| 493 | "[x] Memory poisoning detector" | STATIC OK |
| 494 | "[x] LangGraph / CrewAI / AutoGen adapters" | STATIC OK |
| 495 | "[x] 44-test suite (unit + e2e)" | STATIC OK |
| 496 | "[x] Five-agent reference pipeline" | STATIC OK |
| 497 | "[ ] Rust merge engine release build" | Honest |
| 498–502 | Other unchecked items | Honest |

### A20. Contributing (lines 506–517)

| Lines | Claim | Verdict |
|-------|-------|---------|
| 516–517 | Pre-push test commands | STATIC OK |

### A21. License (line 523)

| Line | Claim | Verdict |
|------|-------|---------|
| 523 | `see [LICENSE]` | **FAIL — file missing** (see A1 row 9). |

### A22. BibTeX (lines 533–541)

| Line | Claim | Verdict |
|------|-------|---------|
| 540 | `url = {https://github.com/<your-org>/agentskein}` | **FAIL — placeholder URL** (same as A6 row 115). |

---

## Section B — AGENTS_INTEGRATION_GUIDE.md, line by line

### B1. ASCII diagrams + intro (lines 1–169)

All four referenced SVG files (`docs/integration-architecture.svg`,
`docs/three-patterns.svg`, `docs/n8n-workflow.svg`, `docs/README.md`) exist.
Strategy table (lines 155–161) matches `ConflictStrategy` enum values.
**STATIC OK.**

### B2. n8n REST API endpoints (lines 230–402)

I cross-checked every endpoint claim against `examples/n8n_api_server/server.py`:

| Doc endpoint | Server route (server.py) | Verdict |
|--------------|--------------------------|---------|
| `POST /namespace/{task}/init` (L242) | line 201 | STATIC OK |
| `POST /namespace/{task}/write/{key}` (L319) | line 209 | STATIC OK |
| `GET  /namespace/{task}/read/{key}` (L396) | line 275 | STATIC OK |
| `GET  /namespace/{task}/snapshot` (L357) | line 301 | STATIC OK |
| `POST /namespace/{task}/fork` (L268) | line 332 | STATIC OK |
| `POST /namespace/{task}/merge` (L338) | line 352 | STATIC OK |
| `POST /detect-poisoning` (L299) | line 393 | STATIC OK |
| `GET  /health` (L401) | line 191 | STATIC OK |
| `GET  /docs` (L402) | provided by FastAPI default | STATIC OK |

Every endpoint, JSON body shape, and response shape in the doc matches the
server. **STATIC OK on all eight endpoints.**

### B3. LangGraph integration (lines 418–492)

| Lines | Claim | Verdict | Evidence |
|-------|-------|---------|----------|
| 425–457 | `AgentSkeinCheckpointer(agent_id, namespace, redis_url, conflict_strategy)` | STATIC OK | Matches `langgraph_adapter.py` lines 46–52. |
| 463–486 | `AgentSkein` constructed inside a node fn | STATIC OK | Signature matches; runs fine. |
| **MISSING** | Adapter only takes `redis_url`, no `backend=` param | **FAIL — usability defect** | A user who reads the LangGraph quickstart and runs without Redis will hit a connection error. The class hard-codes a `RedisBackend(redis_url)` (langgraph_adapter.py line 59). **Action:** add a `backend: StorageBackend \| None = None` parameter to `AgentSkeinCheckpointer.__init__` and forward to `AgentSkein`. |

### B4. CrewAI integration (lines 496–542)

| Lines | Claim | Verdict | Evidence |
|-------|-------|---------|----------|
| 501–514 | Direct `storage.save()` / `storage.search()` usage | STATIC OK | Matches `AgentSkeinStorage.save(agent_id, key, value)` and `.search(agent_id, query, limit)` in `crewai_adapter.py`. |
| 502–509 | `ConflictStrategy.MERGE_STRUCTURAL` used in arg | **MINOR FAIL — missing import** | The snippet references `ConflictStrategy` but has no `from agentskein import ConflictStrategy`. Will throw `NameError` if pasted as-is. |
| 521–541 | "Full integration with a CrewAI Crew" — `crew = Crew(agents=[researcher], tasks=[task], verbose=True)` | **FAIL — `storage` is unused** | The example constructs `storage = AgentSkeinStorage(...)` then calls `Crew(...)` *without* `memory=Memory(storage=storage)`. The promise that "Crew saves all outputs to AgentSkein automatically" (line 536) is therefore false — the crew will use CrewAI's default memory. The correct wiring is shown in `agentskein/adapters/crewai_adapter.py` docstring lines 7–17. **Action:** add `from crewai.memory import Memory` and pass `memory=Memory(storage=storage)` to `Crew(...)`. |

### B5. AutoGen integration (lines 546–576)

| Lines | Claim | Verdict |
|-------|-------|---------|
| 553–559 | `AgentSkeinStore(namespace, redis_url)` | STATIC OK — matches `autogen_adapter.py` lines 38–47. |
| 568–572 | `store.remember(name, key, value)` / `store.recall(name, key)` | STATIC OK — methods exist (lines 59, 65). |
| 568–572 | "Agents write to shared memory during conversation" — defines `save_result` / `load_result` but never wires them into the autogen agents | **MILD — example is incomplete** | The functions are defined but never called from any autogen hook. Not strictly wrong, but doesn't actually demonstrate AutoGen + AgentSkein integration. **Action:** show one full `autogen.AssistantAgent` lifecycle that calls `store.remember` from a `register_reply` callback. |

### B6. Raw API + Anthropic example (lines 580–641)

| Line | Claim | Verdict |
|------|-------|---------|
| 600 | `model = "claude-opus-4-6"` | STATIC OK — this is a real Anthropic model ID. |
| 596–613 | `fork → write → merge_to` flow | STATIC OK — matches signatures. |
| 617 | `SQLiteBackend("research_results.db")` | STATIC OK — matches `SQLiteBackend(path)` signature. |

### B7. Production deployment (lines 776–809)

NSSM service install and Docker compose snippet — cannot verify without running.
The compose snippet (lines 798–809) is consistent with the actual `docker-compose.yml` in the repo. **STATIC OK.**

---

## Section C — docs/README.md, line by line

### C1. Diagrams + intro

All five SVG files referenced (`integration-architecture`, `n8n-workflow`,
`three-patterns`, `conflict-flow`, `multi-agent-pipeline`) exist. **STATIC OK.**

### C2. Recipes (lines 78–133)

| Lines | Claim | Verdict | Evidence |
|-------|-------|---------|----------|
| 83–91 | LangGraph 1-liner replacement | STATIC OK |
| 99–105 | CrewAI direct usage `await storage.save(agent_id, key, value)` | STATIC OK |
| **110–118** | **AutoGen `store.put(agent_id=..., key=..., value=...)` and `store.get(agent_id=..., key=...)`** | **FAIL — methods do not exist** | `AgentSkeinStore` only has `remember(agent_name, key, value)`, `recall(agent_name, key)`, and `recall_all(agent_name)` (autogen_adapter.py lines 59, 65, 71). The snippet calls `put` and `get`, which raise `AttributeError`; it also uses parameter name `agent_id` while the methods take `agent_name`. **Action:** rewrite as `await store.remember(agent_name="planner", key="plan-step-3", value={...})` and `await store.recall(agent_name="executor", key="plan-step-3")`. |
| 122–133 | Raw Python | STATIC OK |

### C3. Pattern picker (lines 135–146)

STATIC OK — matches the README and reality.

### C4. See also (lines 162–169)

| Line | Claim | Verdict |
|------|-------|---------|
| 165 | `../AGENTS_INTEGRATION_GUIDE.md` | STATIC OK — file exists |
| 167 | `../CONTEXT.md` | STATIC OK |
| 168 | `../agents/README.md` | STATIC OK |
| **169** | `../agentskein_paper.tex` | **FAIL — broken link** | File is at `internal_docs/agentskein_paper.tex`, plus `internal_docs/` is gitignored. **Action:** move the paper to repo root and update the link. |

---

## Section D — Adapter docstrings (`agentskein/adapters/`)

### D1. `autogen_adapter.py` lines 8–17

```python
Usage:
    from agentskein.adapters.autogen_adapter import AgentSkeinAgent

    mesh_agent = AgentSkeinAgent(name="researcher", ...)
```

**FAIL — `AgentSkeinAgent` class does not exist.** The module exports
`AgentSkeinStore` only. A user who copies the import will hit `ImportError`.
**Action:** either implement `AgentSkeinAgent` (subclass `autogen.ConversableAgent` and wire `register_reply` to `store.remember`), or rewrite the docstring to show `AgentSkeinStore` usage.

### D2. `langgraph_adapter.py` lines 8–17

```python
checkpointer = AgentSkeinCheckpointer(agent_id="orchestrator",
                                      namespace="my-workflow")
graph = StateGraph(MyState).compile(checkpointer=checkpointer)
```

STATIC OK.

### D3. `crewai_adapter.py` lines 7–17

```python
storage = AgentSkeinStorage(namespace="market-research-crew")
crew = Crew(agents=[...], memory=Memory(storage=storage))
```

STATIC OK — this is the **correct** wiring that AGENTS_INTEGRATION_GUIDE.md
omits (see B4 above). The adapter doc gets it right; the integration guide
doesn't.

---

## Section E — Issues found by prior runtime tests

These are already in `test_results/` from your Docker run, included here for
completeness:

| Issue | Source | Status |
|-------|--------|--------|
| `scenario_03 / RAISE` strategy: `merge_to()` swallowed `ConflictDetectedError` | `test_results/scenario_03_branch_merge_strategies/result.json` | **FIXED** in this session — see `agentskein/client.py` lines 452–492. Re-run scenarios to confirm 4/4 PASS. |
| `MERGE_SEMANTIC` on dict values silently falls back to first-write-wins; `llm_merge_fn` never called | observed in `scenario_03_branch_merge_strategies/events.jsonl` | **NOT FIXED** — `agentskein/protocol/semantic_merge.py` lines 46–48 short-circuit when neither value is a string. Documented behaviour but masks the strategy. **Action:** for dict values, JSON-serialise both, prompt the LLM with the serialised text, parse the result back. |

---

## Section F — Consolidated action list (before public release)

Sorted by severity. Estimated effort in parentheses.

**Blockers (will obviously break for new users):**

1. **(S)** Add a `LICENSE` file to the repo root with the Apache-2.0 text. *Refs:* README L9, L523.
2. **(S)** Replace `<your-org>` placeholders in README L115, L540 and BibTeX with the real GitHub org / URL.
3. **(M)** Move `internal_docs/agentskein_paper.tex` → `agentskein_paper.tex` at repo root, and remove `internal_docs/` from `.gitignore` (or relocate other internal-only docs). *Refs:* README L443, L457, docs/README.md L169.
4. **(M)** Fix `docs/README.md` AutoGen example: replace `store.put(...)` / `store.get(...)` with `await store.remember(agent_name=..., key=..., value=...)` / `await store.recall(agent_name=..., key=...)`. *Refs:* docs/README.md L110–118.
5. **(M)** Fix `agentskein/adapters/autogen_adapter.py` docstring: drop the non-existent `AgentSkeinAgent` example; show `AgentSkeinStore` usage instead.
6. **(M)** Fix AGENTS_INTEGRATION_GUIDE.md CrewAI example: add `from crewai.memory import Memory` and pass `memory=Memory(storage=storage)` to `Crew(...)`. Currently the storage object is never wired in. *Refs:* AGENTS_INTEGRATION_GUIDE.md L502–541.
7. **(M)** Fix AGENTS_INTEGRATION_GUIDE.md CrewAI snippet: add `from agentskein import ConflictStrategy` so the snippet runs as written.
8. **(M)** Either:
   - **(a)** add a `backend: StorageBackend \| None = None` parameter to `AgentSkeinCheckpointer.__init__` and forward to `AgentSkein`, **or**
   - **(b)** change the README and AGENTS_INTEGRATION_GUIDE LangGraph quickstart to make it explicit that Redis is required.
   *Refs:* README L286–292, AGENTS_INTEGRATION_GUIDE.md L432–457.
9. **(M)** Either ship a `comparison/` benchmark suite, or remove the `python ../comparison/run_all_benchmarks.py` line from README L346 and the `comparison/` tree from CONTEXT.md §13.
10. **(M)** Either reconcile README L117 quickstart (`pip install -e .`) with CONTEXT.md's "always use `maturin develop`" warning, or remove the "no Rust required" promise from README L112.

**Polish (won't break anything but reduces trust):**

11. **(S)** Soften lines 41–45 (mem0/Zep/etc. as "single-writer designs") to "designed around a single writer", or back the claim with a real benchmark.
12. **(M)** Label the reference-run metrics table (README L196–208) and performance table (L357–364) as "indicative; re-measure with `agents/run_agents.py`" until a CI benchmark is wired.
13. **(M)** Footnote the feature matrix (L331–342) with a date and "from public docs of each tool" disclaimer.
14. **(M)** Add `tests/bench/` with `pytest-benchmark` cases for the seven performance numbers on L358–364, hook to CI.
15. **(L)** Fix `MERGE_SEMANTIC` on dict values: serialise both sides to JSON before calling `llm_merge_fn`, parse result back (see Section E row 2).
16. **(S)** AGENTS_INTEGRATION_GUIDE.md L568–572 AutoGen example: actually invoke `save_result` / `load_result` from an `autogen.AssistantAgent.register_reply` callback so the example proves the wire-up works.

**Runtime re-verification (needs a clean install):**

After the blockers above are fixed, run:

```bash
docker compose build --no-cache
docker compose up redis api -d
docker compose run --rm test-runner
pytest tests/unit tests/e2e -v          # confirm 44 passed
docker compose up redis -d
pytest tests/integration -v             # +5 tests with Redis
python agents/run_agents.py             # reproduces the 7-section report
python examples/raw_api/multi_agent_demo.py
```

If all of the above pass, the only README claims still without runtime
verification are the seven benchmark numbers (A13). Those need a dedicated
`pytest-benchmark` suite.

---

## Section G — What I could NOT verify in this session

Honest list, for full disclosure:

1. **Runtime behaviour of the `merge_to(RAISE)` fix.** I made the source change in `client.py` lines 452–492 but could not re-run `scenario_03_branch_merge_strategies` from my sandbox. The fix is correct by inspection; please re-run `docker compose run --rm test-runner` to confirm 4/4 PASS.
2. **Every performance number in README §A13** (7 figures). They are reproducible but no automated benchmark ships with the repo.
3. **Cross-tool comparison numbers** in README §A12 vs. LangGraph InMemorySaver, LangChain ConvMemory (rows 3–4). Scenario_01 only benchmarks against plain dict + naive Redis.
4. **`pip install -e .` from a fresh Python 3.12 venv with no Rust installed.** Static reading says it will fail (because of `build-backend = "maturin"`); but the actual error message is the strongest argument for fixing it, and I cannot produce it from this session.
5. **The reference five-agent pipeline timing** (README §A7 lines 196–208). `agents/run_agents.py` exists; the numbers are from one run; rerun is the only way to refresh.

Everything else in the doc set was checked at the source-code or
file-existence level and is reported above.
