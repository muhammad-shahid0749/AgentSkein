<div align="center">

# AgentSkein

**Git-semantics for agent memory — fork, write, merge, resolve.**

*The first open-source library to bring Git-style three-way merge to LLM agent memory.*

[![License](https://img.shields.io/badge/license-Apache--2.0-blue.svg)](LICENSE)
[![Python](https://img.shields.io/badge/python-3.12-blue.svg)](https://python.org)
[![Rust](https://img.shields.io/badge/rust-1.78%2B-orange.svg)](https://rust-lang.org)
[![Tests](https://img.shields.io/badge/tests-44%20passed-brightgreen.svg)](#testing)
[![Backends](https://img.shields.io/badge/backends-Redis%20%7C%20SQLite%20%7C%20InMemory-purple.svg)](#storage-backends)

</div>

---

## What is this?

AgentSkein is a Python library (with a Rust merge kernel) that lets a pool of
LLM agents share a single key-value memory **without losing each other's
writes**. It detects concurrent writes via vector clocks, resolves them via
three-way JSON merge, and exposes branching / merging / attribution / poisoning
detection through a small async API and an HTTP server you can call from any
orchestrator (LangGraph, CrewAI, AutoGen, n8n, raw HTTP, your own loop).

## Why does it exist?

Every popular multi-agent framework — LangGraph, CrewAI, AutoGen — gives each
agent its own isolated memory. The moment two agents need to share and update
the same information, you hit a wall:

```text
Agent A writes  →  market-size = "$2.1B"  →  shared memory
Agent B writes  →  market-size = "$2.4B"  →  shared memory   ← silently overwrites A
Agent C reads   →  market-size = "$2.4B"
                   (you never know A even ran)
```

Tools like **mem0**, **Zep**, **Redis Agent Memory**, and **LangGraph
InMemorySaver** are all single-writer designs. They have no mechanism to
detect concurrent writes, attribute changes, or merge conflicting updates.
At scale — 5–10 agents writing the same coordination state — you get silent
data loss, stale state, and unreproducible runs.

AgentSkein fixes this by borrowing the proven abstractions Git uses for source
code — **branching**, **vector clocks**, and **three-way merge** — and
applying them to agent memory.

---

## At a glance (visual)

Where AgentSkein sits in your stack:

![Integration architecture](docs/integration-architecture.svg)

The three concurrent-write patterns the framework supports (read more in
[`docs/three-patterns.svg`](docs/three-patterns.svg)):

![Three patterns](docs/three-patterns.svg)

The full set of diagrams lives in [`docs/`](docs/) — open
[`docs/README.md`](docs/README.md) for an index plus copy-paste integration
recipes per stack (n8n, LangGraph, CrewAI, AutoGen, raw Python).

---

## The two write patterns (read this section!)

This is the most important page in the docs. The framework's behaviour follows
from a single choice you make at write time.

### Pattern A — disjoint top-level keys *(use this to preserve every writer)*

Every agent writes to a **unique top-level key**. The 3-way merge engine
unions them cleanly because there is nothing to conflict on.

```python
await researcher_1.write("analysis-by-popularity", {...})  # only R1 writes this
await researcher_2.write("analysis-by-activity",   {...})  # only R2 writes this
await researcher_3.write("analysis-by-adoption",   {...})  # only R3 writes this
```

After all three merge to `main`, all three keys are present, each carrying the
originating agent's attribution. **In our reference run (`agents/run_agents.py`),
3 of 3 researcher perspectives were preserved on `main` with zero data loss.**

### Pattern B — shared same-key writes *(use this to detect, then decide)*

All agents write the same key with a flat schema where every scalar field
disagrees. The merge engine **detects** the conflict via vector clocks and
preserves a full audit trail (`chosen_by`, vector clock, severity), but on
flat-schema scalar disagreement it cannot fabricate a union — pick a strategy:

| Strategy            | What happens on a same-key conflict                          |
|---------------------|--------------------------------------------------------------|
| `merge_structural`  | Single survivor per scalar field; non-overlapping fields union; audit trail kept |
| `merge_semantic`    | Conflict routed to an LLM callable that returns a merged value |
| `last_write_wins`   | Latest writer wins; no merging                               |
| `first_write_wins`  | Earliest writer wins (conservative facts)                    |
| `raise`             | Conflict surfaces as `ConflictDetectedError` / HTTP 409; your orchestrator handles it |

> **The single rule.** If you need every writer's view preserved, give each
> writer its own top-level key. If you only need one value with a clean audit
> trail, share the key and pick a strategy. Both are first-class patterns and
> both are demonstrated in the reference pipeline.

---

## 30-second quickstart (no Redis, no Rust required)

```bash
git clone https://github.com/<your-org>/agentskein.git
cd agentskein
python -m venv .venv && source .venv/bin/activate    # Windows: .venv\Scripts\activate
pip install -e .
```

```python
# quickstart.py
import asyncio
from agentskein import AgentSkein
from agentskein.storage.memory_backend import InMemoryBackend

async def main():
    backend = InMemoryBackend()
    agent_a = AgentSkein("agent-A", "task-1", backend=backend); await agent_a.init()
    agent_b = AgentSkein("agent-B", "task-1", backend=backend); await agent_b.init()

    # Pattern A — disjoint keys, both preserved on main
    branch_a = await agent_a.fork("branch-A")
    branch_b = await agent_b.fork("branch-B")
    await branch_a.write("finding-from-A", {"source": "arxiv", "topic": "CRDT"})
    await branch_b.write("finding-from-B", {"source": "neurips", "topic": "vector clocks"})
    await branch_a.merge_to("main")
    await branch_b.merge_to("main")

    snapshot = await agent_a.snapshot()
    for key, value in snapshot.items():
        print(f"{key}: {value}")
    # → finding-from-A: {'source': 'arxiv', ...}
    # → finding-from-B: {'source': 'neurips', ...}   ← both preserved

asyncio.run(main())
```

```bash
python quickstart.py
```

That is the entire library in motion. No external services, no Rust build, no
Docker. For production storage, swap the backend (Redis / SQLite) — same API.

---

## See the full multi-agent pipeline in 5 seconds

The repository ships a reference five-agent pipeline that exercises every
feature against the live GitHub Search API:

```text
Orchestrator
  ├── Researcher-1  (POPULARITY — ranks by stars)
  ├── Researcher-2  (ACTIVITY   — ranks by last commit)
  ├── Researcher-3  (ADOPTION   — ranks by forks)
  └── Safety-Monitor (8 injection tests + storm test + repo-description scan)
       └── (all four run concurrently in Phase 1)
Analyst    (reads each researcher's branch → builds conflict-resolution proof)
Writer     (renders the seven-section intelligence report)
```

Run it:

```bash
# Terminal 1 — start the HTTP API (FastAPI + uvicorn)
python examples/n8n_api_server/server.py

# Terminal 2 — kick off the orchestrator
python agents/run_agents.py
```

This produces `agents/ai_ecosystem_report.txt` (~500 lines, 7 sections):

| Section | Content                                                       |
|---------|---------------------------------------------------------------|
| 1       | **Executive Summary** — verdict on the framework's claim      |
| 2       | **Per-agent activity timeline** — every event with timestamps |
| 3       | **Conflict resolution analysis** — patterns A, B, C dissected |
| 4       | **Research statistics** — live GitHub data                    |
| 5       | **Safety analysis** — injection / storm / scan results        |
| 6       | **Verification metrics** — aggregate event counts             |
| 7       | **Efficiency analysis** — phase timing, concurrency speedup, throughput |

Reference run on `InMemoryBackend` (5-repo fixture, sandbox):

| Metric                                            | Value                  |
|---------------------------------------------------|------------------------|
| Pipeline wall-clock                               | 3.76 s                 |
| Phase 1 wall-clock (3 researchers concurrent)     | 3.12 s                 |
| Concurrency speedup factor                        | 2.19× (ideal 3.00×)    |
| Avg merge cost per branch                         | 211 ms                 |
| End-to-end write throughput                       | 5.8 writes / s         |
| **Perspectives preserved (disjoint pattern)**     | **3 / 3**              |
| Conflict detected on shared `verdict` key         | yes (vector clocks)    |
| Repos found by ≥ 2 researchers (auto-merged)      | 5                      |
| Safety score                                      | 8 / 9                  |

---

## Architecture

```text
┌─────────────────────────────────────────────────────────────┐
│                  Your agent framework                        │
│       LangGraph │ CrewAI │ AutoGen │ n8n │ Raw HTTP          │
└─────────────────────┬───────────────────────────────────────┘
                      │  adapter layer  (FastAPI server, or in-process import)
┌─────────────────────▼───────────────────────────────────────┐
│                   AgentSkein client                          │
│  write()  read()  fork()  merge_to()  snapshot()  delete()  │
│                                                              │
│  • Vector clock conflict detection                           │
│  • base_value ancestor tracking (true 3-way merge)           │
│  • Exponential backoff lock retry                            │
│  • Embedding hook  (pluggable)                               │
│  • LLM merge hook  (pluggable)                               │
└──────────────┬────────────────────────────────┬─────────────┘
               │                                │
  ┌────────────▼───────────┐      ┌─────────────▼────────────┐
  │   Conflict Resolution  │      │    Storage Backend       │
  │                        │      │                          │
  │  LAST_WRITE_WINS       │      │  Redis    (production)   │
  │  FIRST_WRITE_WINS      │      │  SQLite   (offline/dev)  │
  │  MERGE_STRUCTURAL ──►  │      │  InMemory (testing)      │
  │    Rust 3-way merge    │      │                          │
  │  MERGE_SEMANTIC ────►  │      │  All backends implement  │
  │    LLM callable        │      │  lazy copy-on-write      │
  │  RAISE                 │      │  branch fall-through     │
  └────────────────────────┘      └──────────────────────────┘
               │
  ┌────────────▼───────────┐
  │  Poisoning Detection   │
  │  • Injection patterns  │
  │  • Overwrite storms    │
  └────────────────────────┘
```

---

## Storage backends

| Backend           | When to use                                | Setup                                  |
|-------------------|--------------------------------------------|----------------------------------------|
| `InMemoryBackend` | Unit tests, quickstart, single-process dev | None — built in                        |
| `SQLiteBackend`   | Offline / embedded / air-gapped            | `pip install aiosqlite`                |
| `RedisBackend`    | Production, multi-process, distributed     | `docker compose up redis -d`           |

```python
# Pick the backend at construction time — everything else stays the same.
from agentskein.storage.redis_backend  import RedisBackend
from agentskein.storage.sqlite_backend import SQLiteBackend

mesh = AgentSkein("agent-1", "task-1", backend=RedisBackend("redis://localhost:6379/0"))
# or
mesh = AgentSkein("agent-1", "task-1", backend=SQLiteBackend("./mesh.db"))
```

---

## Framework integrations

| Framework        | Adapter                       | What it replaces                       |
|------------------|-------------------------------|----------------------------------------|
| LangGraph ≥ 0.2  | `AgentSkeinCheckpointer`      | `InMemorySaver` / `SqliteSaver`        |
| CrewAI           | `AgentSkeinStorage`           | `RAGStorage` / `SQLiteStorage`         |
| AutoGen          | `AgentSkeinStore`             | Custom agent memory dict               |
| n8n / Make / Zapier | HTTP API (`server.py`)     | DIY shared state                       |
| Raw API          | `AgentSkein` class directly   | Nothing — add memory to any loop       |

```python
# Example: LangGraph checkpointer
from agentskein.adapters.langgraph_adapter import AgentSkeinCheckpointer

checkpointer = AgentSkeinCheckpointer(
    agent_id="orchestrator",
    namespace="my-workflow",
    redis_url="redis://localhost:6379/0",
)
graph = StateGraph(MyState).compile(checkpointer=checkpointer)
```

Full integration examples for each framework are in [`AGENTS_INTEGRATION_GUIDE.md`](AGENTS_INTEGRATION_GUIDE.md).

---

## Per-stack integration recipes

Copy-paste recipes for every common stack live in
[`docs/README.md#integration-recipes-by-stack`](docs/README.md#integration-recipes-by-stack):

| Stack                    | What you do                                                  |
|--------------------------|--------------------------------------------------------------|
| **n8n / Make / Zapier**  | Three HTTP Request nodes against `:8765` — see [`docs/n8n-workflow.svg`](docs/n8n-workflow.svg) |
| **LangGraph**            | Swap your checkpointer for `AgentSkeinCheckpointer`          |
| **CrewAI**               | Swap your storage for `AgentSkeinStorage`                    |
| **AutoGen**              | Use `AgentSkeinStore` as the team-wide memory                |
| **Raw Python / your loop** | Import `AgentSkein` directly, pick an `agent_id`, write    |

The protocol underneath every recipe is the same — see
[`docs/conflict-flow.svg`](docs/conflict-flow.svg) for the six-step write
pipeline that runs on every call.

---

## How it compares
We benchmarked AgentSkein against four common alternatives on the
multi-writer concurrent-write test (5 agents × 10 shared keys):

| Approach              | Conflict detected? | Agents surviving | Data loss % |
|-----------------------|--------------------|------------------|-------------|
| Plain Python dict     | ✗                  | 1                | 80 %        |
| Redis (fakeredis)     | ✗                  | 1                | 80 %        |
| LangGraph InMemorySaver | ✗                | 1                | 80 %        |
| LangChain ConvMemory  | ✗                  | 1                | 80 %        |
| **AgentSkein**        | **✓**              | **5**            | **0 %**     |

Feature matrix:

| Feature                  | mem0   | Zep    | Redis  | Letta  | Automerge | **AgentSkein** |
|--------------------------|--------|--------|--------|--------|-----------|----------------|
| Multi-writer detection   | ✗      | ✗      | ✗      | ✗      | n/a (CRDT) | ✓              |
| Three-way JSON merge     | ✗      | ✗      | ✗      | ✗      | ✓ (CRDT)  | ✓              |
| Plain JSON value model   | ✓      | ✓      | ✓      | ✓      | ✗         | ✓              |
| Branching                | ✗      | ✗      | ✗      | ✗      | ✓         | ✓              |
| Attribution per write    | part.  | ✗      | ✗      | part.  | ✓         | ✓              |
| Poisoning detection      | ✗      | ✗      | ✗      | ✗      | ✗         | ✓              |
| Offline mode (SQLite)    | ✗      | ✗      | ✗      | ✗      | ✓         | ✓              |
| LangGraph / CrewAI / AutoGen adapter | part. | ✗ | ✗   | ✗      | ✗         | ✓              |
| Apache-2.0 licence       | ✓      | ✗      | ✓      | ✓      | ✓         | ✓              |

Reproduce these numbers:

```bash
python ../comparison/run_all_benchmarks.py
```

---

## Performance (single-backend benchmarks)

On `InMemoryBackend`, Python 3.12, no Rust extension required for these
numbers:

| Operation                                  | Performance         |
|--------------------------------------------|---------------------|
| Sequential writes (1,000 keys)             | ~32,800 ops / s     |
| Sequential reads (1,000 keys)              | ~245,600 ops / s    |
| `fork()` on 1,000-entry namespace          | 1.59 ms (O(1))      |
| `VectorClock.increment()`                  | ~521,000 ops / s    |
| `VectorClock.concurrent_with()`            | ~378,000 ops / s    |
| 10 concurrent agents × 100 writes each     | ~60,500 writes / s  |
| Rust 3-way merge engine (release build)    | 10,000+ merges / s  |

The Rust engine is built with `maturin develop` and gives the fastest
structural-merge path. Without it the library falls back to a pure-Python
merge.

---

## Installation

### Minimum (quickstart, in-memory only)

```bash
pip install -e .
```

### Full (production: Rust merge + Redis backend)

```bash
# 1. Rust toolchain
curl --proto '=https' --tlsv1.2 -sSf https://sh.rustup.rs | sh -s -- -y

# 2. Build the Rust extension
pip install maturin
maturin develop

# 3. Start Redis
docker compose up redis -d
```

Verify the Rust merge engine is wired in:

```bash
python -c "from agentskein._core import py_three_way_merge; print('Rust OK')"
```

---

## Testing

```bash
# Unit + e2e — no Docker, no Rust needed
pytest tests/unit/ tests/e2e/ -v
# → 44 passed in 0.57s

# Integration tests with Redis (requires Docker)
docker compose up redis -d
pytest tests/integration/ -v

# Rust unit tests
cargo test --manifest-path core/Cargo.toml
```

---

## Project layout

```text
agentskein/
├── agentskein/                   ← Python package
│   ├── client.py                 ← main AgentSkein class
│   ├── protocol/                 ← MemoryEntry, VectorClock, Branch, Conflict, Poisoning
│   ├── storage/                  ← Redis / SQLite / InMemory backends
│   └── adapters/                 ← LangGraph / CrewAI / AutoGen
├── core/src/lib.rs               ← Rust three-way JSON merge (PyO3)
├── examples/
│   ├── n8n_api_server/server.py  ← FastAPI HTTP server (start this first)
│   ├── raw_api/                  ← Async examples in pure Python
│   ├── langgraph/                ← LangGraph integration demo
│   └── crewai/                   ← CrewAI integration demo
├── agents/                       ← Five-agent reference pipeline
│   ├── run_agents.py             ← entry point
│   ├── orchestrator_agent.py
│   ├── researcher_agent.py
│   ├── analyst_agent.py
│   ├── safety_agent.py
│   ├── writer_agent.py
│   └── ai_ecosystem_report.txt   ← regenerated each run, 7 sections
├── tests/                        ← unit + e2e + integration (44 passing)
├── agentskein_paper.tex          ← 7-page technical report
├── README.md                     ← you are here
├── CONTEXT.md                    ← full LLM context (every file, every algorithm)
└── AGENTS_INTEGRATION_GUIDE.md   ← how to wire AgentSkein into your agents
```

---

## Documentation

- [`AGENTS_INTEGRATION_GUIDE.md`](AGENTS_INTEGRATION_GUIDE.md) — how to plug
  AgentSkein into n8n, LangGraph, CrewAI, AutoGen, or a raw HTTP loop.
- [`CONTEXT.md`](CONTEXT.md) — full architectural reference (every file, every
  algorithm, every quirk). Useful for new contributors.
- [`agentskein_paper.tex`](agentskein_paper.tex) — 7-page technical report
  covering data model, algorithms, related work, evaluation, and limitations.
- [`agents/ai_ecosystem_report.txt`](agents/ai_ecosystem_report.txt) — sample
  output from the reference pipeline; regenerated every run.

---

## Design notes

**Why Rust for the merge engine?** Three-way merge on JSON dicts is CPU-bound.
Python dicts are slow for this. Rust gives memory safety and the 10k+ ops/sec
target with no GIL contention. PyO3 makes the Python interface seamless.

**Why vector clocks instead of timestamps?** Clocks on distributed machines
drift. A timestamp comparison between two agents on different machines is
unreliable. Vector clocks give *causal* ordering — we know with certainty
whether one write happened-before another or whether they were truly
concurrent.

**Why lazy copy-on-write for branches?** An eager copy of a 10,000-entry
namespace takes hundreds of milliseconds and bloats storage. With lazy CoW,
`fork()` is always O(1) — just a pointer to the parent. The child only
materialises entries it actually writes.

**Why store `base_value` on every entry?** Without the common ancestor,
three-way merge degrades to a two-way merge. Two-way merge cannot
distinguish "both sides added this key" from "one side added it and the
other deleted it." Storing the previous value as `base_value` on every write
gives the merge engine a real ancestor to reason from.

---

## Roadmap

- [x] InMemory / SQLite / Redis backends
- [x] Vector clocks + three-way merge + branching
- [x] Memory poisoning detector
- [x] LangGraph / CrewAI / AutoGen adapters
- [x] 44-test suite (unit + e2e)
- [x] Five-agent reference pipeline with 7-section auto-generated report
- [ ] Rust merge engine release build via `maturin build --release`
- [ ] Multi-node Redlock (true distributed locking across a Redis cluster)
- [ ] Semantic search using stored embeddings (cosine similarity)
- [ ] Memory TTL expiry background worker
- [ ] Web dashboard (replace the Rich CLI)
- [ ] PyPI publish

---

## Contributing

Issues and pull requests are welcome. For larger changes please open an issue
first to discuss what you'd like to change.

When contributing:
- Keep changes focused; one logical change per PR.
- Add tests covering new behaviour (unit + e2e where relevant).
- For changes to the merge engine, update both the Rust unit tests and the
  Python coverage.
- Run `pytest tests/unit/ tests/e2e/` and `cargo test --manifest-path core/Cargo.toml`
  before pushing.

---

## License

Apache-2.0 — see [`LICENSE`](LICENSE).

---

## Citing this work

If you use AgentSkein in research, please cite the accompanying technical
report:

```bibtex
@techreport{shahid2026agentskein,
  title  = {AgentSkein: Cross-Agent Shared Memory with Git-Semantics and
            Conflict Resolution for Multi-Agent LLM Systems},
  author = {Shahid, Muhammad},
  year   = {2026},
  note        = {Open-source release; see project README for details},
  url    = {https://github.com/<your-org>/agentskein}
}
```
