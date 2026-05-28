# AgentSkein — Complete LLM Context File

> This file gives an LLM (or any new contributor) a full understanding of the
> AgentSkein codebase in a single read. It covers purpose, architecture, every
> file, every key algorithm, all known quirks, and how to run everything.

---

## 1. What AgentSkein Is

AgentSkein is an open-source Python library (Apache-2.0) that solves the
**multi-writer problem** in LLM agent systems. To our knowledge it is the
**first open-source library to bring Git-style three-way merge to LLM
agent memory**, with empirical comparison against five baselines and
adapters for LangGraph, CrewAI, and AutoGen.

**The problem:** When two AI agents write to the same shared memory key at the
same time, existing tools (mem0, Zep, Redis Agent Memory, LangGraph
InMemorySaver) silently discard one write. There is no notification, no
conflict detection, and no merge. Letta (formerly MemGPT) introduces shared
memory blocks between agents but treats them as last-write-wins. Automerge
gives CRDT semantics over JSON but at the cost of a CRDT-specific value model
and opaque history; AgentSkein is the complementary "Git for agent memory"
design point — plain JSON, vector clocks, three-way merge with a recorded
common ancestor.

**The solution:** AgentSkein applies Git-branching semantics to agent memory:
- Every write carries a **vector clock** — if two clocks are concurrent, a
  conflict is detected.
- Conflicts are resolved by a **three-way JSON merge** (implemented in Rust)
  that combines non-conflicting changes from both sides.
- Agents work in **isolated branches** (O(1) lazy copy-on-write), then merge
  back to main — just like feature branches in Git.
- A **poisoning detector** guards against prompt-injection payloads written
  into shared memory by compromised agents.

**The two patterns you will actually use:**

1. **Disjoint-key pattern.** Each writer picks a unique top-level key. The
   3-way merge engine unions cleanly — every writer's contribution is
   preserved on `main`. This is the pattern that demonstrates "zero data
   loss across concurrent writers."
2. **Same-key pattern.** All writers write the same key with disagreeing
   scalar fields. The framework **detects** the conflict via vector clocks
   and preserves the audit trail; with `merge_structural` the resolved
   value reflects a single survivor per scalar field. Choose `merge_semantic`
   (LLM merge) or `raise` (HTTP 409) for richer handling.

The end-to-end demo at `agents/run_agents.py` exercises both patterns
against the live GitHub Search API and writes a seven-section report to
`agents/ai_ecosystem_report.txt` that includes per-agent activity timelines
and pipeline efficiency metrics (phase timing, concurrency speedup, merge
cost, throughput).

**Tagline:** "Git-semantics for agent memory — fork, write, merge, resolve."

---

## 2. Repository Layout

```
agentskein/                     ← project root (contains pyproject.toml)
├── agentskein/                 ← Python package
│   ├── __init__.py             ← public API surface (import from here)
│   ├── client.py               ← AgentSkein class — the main entry point
│   ├── cli.py                  ← CLI: watch / snapshot / branches / write
│   ├── protocol/
│   │   ├── types.py            ← MemoryEntry, VectorClock, Branch, Conflict
│   │   ├── namespace.py        ← NamespaceConfig, NamespaceState
│   │   ├── semantic_merge.py   ← LLM merge prompt + callable interface
│   │   └── poisoning.py        ← PoisoningDetector (injection + storm)
│   ├── storage/
│   │   ├── base.py             ← StorageBackend protocol (interface)
│   │   ├── redis_backend.py    ← Redis + Redlock locking
│   │   ├── sqlite_backend.py   ← SQLite via aiosqlite (offline/embedded)
│   │   └── memory_backend.py   ← In-process dict (unit tests / dev)
│   └── adapters/
│       ├── langgraph_adapter.py ← BaseCheckpointSaver for LangGraph ≥ 0.2
│       ├── crewai_adapter.py   ← CrewAI RAGStorage interface
│       └── autogen_adapter.py  ← AutoGen shared memory store
├── core/                       ← Rust merge engine
│   ├── Cargo.toml
│   └── src/lib.rs              ← three-way JSON merge via PyO3
├── tests/
│   ├── unit/                   ← No Redis, no Docker needed
│   │   ├── test_vector_clock.py
│   │   ├── test_poisoning.py
│   │   ├── test_memory_backend.py
│   │   └── test_client_inmemory.py
│   ├── integration/            ← Requires Docker (Redis via testcontainers)
│   │   └── test_redis_backend.py
│   └── e2e/
│       └── test_multi_agent_scenarios.py
├── examples/
│   ├── raw_api/multi_agent_demo.py
│   ├── langgraph/langgraph_example.py
│   └── crewai/crewai_example.py
├── comparison/                 ← Benchmark vs. existing tools
│   ├── run_all_benchmarks.py
│   ├── approaches/
│   │   ├── 01_plain_dict/benchmark.py
│   │   ├── 02_simple_redis/benchmark.py
│   │   ├── 03_langgraph_inmemory/benchmark.py
│   │   ├── 04_langchain_conv_memory/benchmark.py
│   │   └── 05_agentskein/benchmark.py
│   └── results/
│       ├── comparison_report.txt
│       └── raw_results.json
├── pyproject.toml              ← build config (maturin for Rust extension)
├── Cargo.toml                  ← Rust workspace root
├── Dockerfile                  ← two-stage build (Rust in builder only)
├── docker-compose.yml          ← Redis + RedisInsight + demo
├── setup_windows.ps1           ← one-shot Windows environment setup
├── README.md                   ← full project README
├── CONTEXT.md                  ← this file
└── agentskein_paper.tex/.pdf   ← academic paper
```

---

## 3. Key Data Types (`agentskein/protocol/types.py`)

### `VectorClock`
A Pydantic model with `clocks: dict[str, int]`.
- `increment(agent_id)` → new clock with agent's counter +1
- `dominates(other)` → True if self ≥ other in every component
- `concurrent_with(other)` → True if neither dominates (= conflict detected)
- `merge(other)` → component-wise max (used after resolution)

### `MemoryEntry`
The atomic storage unit. Key fields:
- `id: str` — ULID (universally unique + chronologically sortable)
- `namespace: str` — logical container (e.g. `"task-42"`)
- `branch: str` — branch name, default `"main"`
- `key: str` — human-readable key
- `value: Any` — arbitrary JSON-serialisable content
- `base_value: Any` — **common ancestor** for three-way merge [B1]
- `embedding: list[float] | None` — vector embedding (populated by embedding_fn)
- `agent_id: str` — which agent wrote this
- `clock: VectorClock` — causal clock at time of write
- `created_at / updated_at: float` — Unix timestamps

### `Branch`
- `name: str` — branch name
- `parent_branch: str` — pointer to parent for CoW read fall-through [B3]
- `created_by: str` — agent_id that created the branch
- `is_merged: bool` — True after merge_to() completes

### `ConflictStrategy` (StrEnum)
Five strategies:
- `LAST_WRITE_WINS` — B silently overwrites A (lossy but simple)
- `FIRST_WRITE_WINS` — A's value is preserved
- `MERGE_STRUCTURAL` — Rust three-way JSON merge
- `MERGE_SEMANTIC` — LLM callable merges textual conflicts
- `RAISE` — raises `ConflictDetectedError` to the application

---

## 4. The AgentSkein Client (`agentskein/client.py`)

The `AgentSkein` class is the single entry point for all agent interactions.

### Constructor parameters
```python
AgentSkein(
    agent_id: str,
    namespace: str,
    branch: str = "main",
    backend: StorageBackend | None = None,  # default: RedisBackend
    redis_url: str = "redis://localhost:6379/0",
    conflict_strategy: ConflictStrategy = ConflictStrategy.MERGE_STRUCTURAL,
    lock_timeout_ms: int = 3000,
    embedding_fn: Callable | None = None,   # async (value) → list[float]
    llm_merge_fn: Callable | None = None,   # async (prompt: str) → str
)
```

### The write path (most important method)
`await mesh.write(key, value)` follows this exact sequence:
1. Acquire distributed lock on `"{namespace}:{branch}:{key}"` with **exponential
   backoff** (delays: 20ms, 40ms, 80ms, 160ms, 320ms, 640ms + jitter).
2. Read current stored entry.
3. Compute `new_clock = local_clock.increment(agent_id)`.
4. Check:
   - `existing is None` → first write, no conflict. `base_value = None`.
   - `new_clock.concurrent_with(existing.clock)` → conflict → call `_resolve_conflict()`.
   - otherwise → causally ordered update. `base_value = existing.value`.
5. If `embedding_fn` provided → `entry.embedding = await embedding_fn(value)`.
6. Save entry to backend.
7. Update `local_clock = new_clock`.
8. Release lock.

### Conflict resolution (`_resolve_conflict`)
Dispatches on strategy:
- `RAISE` → `raise ConflictDetectedError(conflict)`
- `LAST_WRITE_WINS` → use `entry_ours.value`
- `FIRST_WRITE_WINS` → use `entry_theirs.value`
- `MERGE_STRUCTURAL` → call `_structural_merge()` → Rust engine
- `MERGE_SEMANTIC` → call `_semantic_merge()` → `llm_merge_fn` if provided,
  else falls back to structural merge

### Three-way merge base value
`_structural_merge()` uses `conflict.entry_theirs.base_value` (not `{}`) as
the common ancestor. This is **fix B1** — without the real base, the merge
algorithm cannot distinguish "both sides added a key" from "one side deleted it".

### Branching (fork / merge_to)
`fork(branch_name)`:
- Creates a `Branch` record with `parent_branch = self.branch_name`.
- **No entries are copied** — O(1) operation regardless of namespace size.
- Returns a new `AgentSkein` instance scoped to `branch_name`.
- Reads on the child branch fall through to the parent via `get_entry()` CoW
  logic in all three backends. [B3]

`merge_to(target_branch)`:
- Reads all entries from `self.branch_name`.
- Writes each to `target_branch` (conflict detection applies).
- Marks branch as `is_merged = True`.

---

## 5. Storage Backends

All three backends implement the same `StorageBackend` protocol
(`agentskein/storage/base.py`). They are drop-in replaceable.

### Copy-on-Write read fall-through [B3]
Every backend's `get_entry(namespace, branch, key)` method:
1. Looks up the entry for the given branch.
2. On a miss, looks up the branch record to find `parent_branch`.
3. Recursively retries with the parent branch.
4. Returns `None` only if the key is not found all the way up to the root.

This is what makes `fork()` O(1) — entries are never copied, only read from
the parent on demand.

### `InMemoryBackend` (`storage/memory_backend.py`)
- Uses Python dicts + `asyncio.Lock`.
- Not safe for multi-process use.
- Ideal for unit tests and rapid prototyping.
- No external services required.

### `RedisBackend` (`storage/redis_backend.py`)
- Uses `redis.asyncio` (async redis-py client).
- Key schema:
  - `mm:ns:{namespace}` → NamespaceState JSON
  - `mm:entry:{namespace}:{branch}:{key}` → MemoryEntry JSON
  - `mm:branch:{namespace}:{branch_name}` → Branch JSON
  - `mm:lock:{resource}` → lock token with TTL
  - `mm:idx:{namespace}:{branch}` → sorted set of keys by creation time
- Locking: `SET NX PX` + Lua check-and-delete for release (single-node Redlock).
- Connection pool: `max_connections=50`.

### `SQLiteBackend` (`storage/sqlite_backend.py`) [B9]
- Uses `aiosqlite` for non-blocking I/O.
- Four tables: `namespaces`, `entries`, `branches`, `locks`.
- Locking uses `INSERT OR FAIL` on the `locks` table (SQLite single-writer).
- Survives close/reopen — data is fully persisted.
- No external services — works completely offline.
- Ideal for local development and CI without Docker.

---

## 6. The Rust Merge Engine (`core/src/lib.rs`)

Compiled as a Python extension module `agentskein._core` via PyO3 + maturin.

### Exposed Python functions
```python
from agentskein._core import py_three_way_merge, py_compute_diff

result_json = py_three_way_merge(base_json, ours_json, theirs_json)
# Returns JSON string: {"merged": {...}, "auto_resolved_keys": [...], "conflict_keys": [...], "is_clean": bool}

diff_json = py_compute_diff(base_json, changed_json)
# Returns JSON string: ["+ new_key", "~ changed_key", "- removed_key"]
```

### Algorithm
For each key across `base ∪ ours ∪ theirs`:
1. Only ours has it → take ours (new addition)
2. Only theirs has it → take theirs (new addition)
3. Both have it, same value → take either (agreement)
4. Ours changed from base, theirs didn't → take ours
5. Theirs changed from base, ours didn't → take theirs
6. Both changed to same value → take either (agreement)
7. Both are nested dicts → recurse
8. Both changed to different values → add to `conflict_keys` (escalate)

### Python fallback
If `agentskein._core` is not compiled (Rust not installed), `client.py`
catches the `ImportError` and falls back to a Python dict merge:
```python
return {**theirs_val, **ours_val}  # ours wins on conflict
```
This is weaker (no base, no recursive merge) but keeps the package functional.

---

## 7. Memory Poisoning Detection (`agentskein/protocol/poisoning.py`)

`PoisoningDetector` is stateful and watches write patterns per namespace.

### Detection 1: Prompt injection patterns
Checks every value string against compiled regexes:
- `ignore [all] previous instructions`
- `disregard [all] prior [instructions/context]`
- `you are now a[n] ...`
- `<|system|>` (OpenAI style)
- `[INST] ... [/INST]` (LLaMA style)
- `### Human: / ### Assistant:` (HuggingFace style)

Raises `PoisoningAlert` with `severity="high"`.

### Detection 2: Overwrite storm
Sliding window per agent. If an agent makes more than `overwrite_storm_threshold`
(default: 20) writes within `storm_window_seconds` (default: 1.0s), raises
`PoisoningAlert` with `severity="medium"`.

The detector **logs** alerts but does not block writes by default. To block,
call `detector.check()` before writing and raise if alerts are returned.

---

## 8. Framework Adapters

### LangGraph (`adapters/langgraph_adapter.py`) [B5]
`AgentSkeinCheckpointer` extends `BaseCheckpointSaver` (LangGraph ≥ 0.2).
- Implements: `aput`, `aget_tuple`, `alist` (async generator), `put`, `get_tuple`, `list`.
- Checkpoint key: `ckpt:{thread_id}:{checkpoint_ns}`
- **Fix B5**: The original used a plain class without extending `BaseCheckpointSaver`.
  LangGraph ≥ 0.2 requires the proper ABC.

### CrewAI (`adapters/crewai_adapter.py`)
`AgentSkeinStorage` implements `save()` / `search()` / `reset()`.
- If `embedding_fn` provided: `search()` does cosine similarity.
- Otherwise: `search()` does substring text matching.

### AutoGen (`adapters/autogen_adapter.py`)
`AgentSkeinStore` with `remember()` / `recall()` / `recall_all()`.
- One `AgentSkein` instance per agent name.
- All agents share the same namespace.

---

## 9. LLM Semantic Merge (`agentskein/protocol/semantic_merge.py`)

`semantic_merge(key, value_ours, value_theirs, agent_ours, agent_theirs, llm_callable)`

Builds this prompt and calls `await llm_callable(prompt)`:

```
You are a careful editor helping merge two versions of a memory entry.

KEY: {key}

VERSION A (written by {agent_a}):
{value_a}

VERSION B (written by {agent_b}):
{value_b}

Task: Produce a single merged version that:
1. Preserves all unique information from both versions
2. Resolves contradictions by favouring the more specific or recent claim
3. Maintains factual accuracy
4. Is concise — do not add commentary or explanation

Output ONLY the merged content, nothing else.
```

For non-string values, returns `value_ours` without calling the LLM.

---

## 10. CLI (`agentskein/cli.py`)

Uses Click + Rich. Commands:

| Command | Description |
|---------|-------------|
| `agentskein watch -n <ns>` | Live dashboard, refreshes every 2s |
| `agentskein snapshot -n <ns>` | Print all key-value pairs |
| `agentskein branches -n <ns>` | List all branches |
| `agentskein write -n <ns> -k <key> -v <json>` | Write a value |

The `watch` command creates the backend and mesh instance **once outside the
loop** [B6]. The original created a new connection on every tick (connection
leak).

---

## 11. The Public API (`agentskein/__init__.py`) [B10]

```python
from agentskein import (
    AgentSkein,           # main client class
    ConflictDetectedError,# raised by RAISE strategy
    MemoryEntry,          # storage type
    Branch,               # branch type
    Conflict,             # conflict record
    Resolution,           # resolution outcome
    VectorClock,          # causal clock
    ConflictStrategy,     # enum of 5 strategies
    NamespaceConfig,      # namespace settings
    NamespaceState,       # runtime namespace state
    InMemoryBackend,      # in-process backend
    RedisBackend,         # Redis backend
    SQLiteBackend,        # SQLite backend
)
```

**Fix B10**: The original left this file empty, causing `ImportError` on any
`from agentskein import X` statement.

---

## 12. All 11 Bugs Fixed Before Coding

These bugs were found during review of the original build guide and fixed
before any code was written:

| ID | Bug | Fix |
|----|-----|-----|
| B1 | `_structural_merge` used `{}` as base → broken 3-way merge | `MemoryEntry.base_value` stores real ancestor |
| B2 | `fork()` reused parent entry IDs → ID collisions | Superseded by B3 (no copy at all) |
| B3 | `fork()` eagerly copied all N entries → O(N) | Lazy CoW: `get_entry()` falls through to parent |
| B4 | Lock retry: one attempt + fixed 50ms sleep → thundering herd | Exponential backoff with jitter, 6 attempts |
| B5 | LangGraph adapter didn't extend `BaseCheckpointSaver` | Fully rewritten for LangGraph ≥ 0.2 |
| B6 | `watch` CLI: new Redis connection on every loop tick | Backend created once outside the loop |
| B7 | Dockerfile: `pip install -e ".[dev]"` in prod image | Two-stage build; only `.whl` in final image |
| B8 | `embedding` field defined but never populated | `embedding_fn` hook wired into `_do_write()` |
| B9 | SQLite backend promised in spec, never written | Full `SQLiteBackend` with CoW fall-through |
| B10 | `__init__.py` was empty → `ImportError` on import | Complete public API exported |
| B11 | `MERGE_SEMANTIC` always fell back to structural merge | `llm_merge_fn` injected at construction time |

---

## 13. How to Run

### Prerequisites
- Python 3.12+
- Rust (stable) — for the Rust merge engine
- Docker Desktop — for Redis (optional; SQLite works offline)

### One-shot Windows setup
```powershell
# Run as Administrator
Set-ExecutionPolicy RemoteSigned -Scope CurrentUser
cd "<path-to-agentskein>"
.\setup_windows.ps1
```

### Manual setup (any OS)
```bash
# Install Rust
curl --proto '=https' --tlsv1.2 -sSf https://sh.rustup.rs | sh

# Create venv
python3.12 -m venv .venv
source .venv/bin/activate        # Windows: .venv\Scripts\Activate.ps1

# Install runtime deps (bypass maturin build backend)
pip install redis aiosqlite pydantic anyio httpx rich click structlog \
            opentelemetry-api opentelemetry-sdk ulid-py

# Install dev deps
pip install pytest pytest-asyncio pytest-cov ruff mypy fakeredis

# Install maturin and compile the Rust extension
# This ALSO installs the agentskein package in editable mode
pip install maturin
maturin develop

# Verify
python -c "from agentskein import AgentSkein; print('OK')"
```

### Why `pip install -e .` doesn't work directly
`pyproject.toml` uses `maturin` as the build backend. This means `pip install -e .`
tries to compile Rust code. If Rust is not installed or the compilation fails,
the package is not installed at all. **Always use `maturin develop`** for
editable installs with this project.

### If you can't compile Rust right now
Add the project root to `PYTHONPATH`:
```powershell
# Windows (PowerShell)
$env:PYTHONPATH = "<path-to-agentskein>"
```
```bash
# Linux/macOS
export PYTHONPATH=/path/to/agentskein
```
This makes the package importable without installation. The Rust merge engine
will be unavailable, but the Python fallback is automatic.

### Running the multi-agent demo
```bash
# No Redis needed (uses InMemoryBackend automatically)
python examples/raw_api/multi_agent_demo.py

# With Redis
docker compose up redis -d
python examples/raw_api/multi_agent_demo.py
```

### Running tests
```bash
# Unit + E2E (no Redis, no Docker)
pytest tests/unit/ tests/e2e/ -v --override-ini="addopts="

# Integration (requires Docker)
docker compose up redis -d
pytest tests/integration/ -v --override-ini="addopts="
```

### Running comparison benchmarks
```bash
cd comparison/
python run_all_benchmarks.py
# Results written to comparison/results/comparison_report.txt
```

---

## 14. Benchmark Results (Comparison vs. Existing Tools)

Tested: 5 agents × 10 shared keys written concurrently.

| Approach | Data Loss | Conflict Detected |
|---|---|---|
| Plain Python Dict | 80% | NO |
| Simple Redis | 80% | NO |
| LangGraph InMemorySaver | 80% | NO |
| LangChain ConvMemory | 80% | NO |
| **AgentSkein** | **0%** | **YES** |

Performance (InMemoryBackend):

| Operation | Result |
|---|---|
| Sequential writes | 32,803 ops/sec |
| Sequential reads | 245,647 ops/sec |
| 10 concurrent agents, 100 writes each | 60,572 ops/sec |
| VectorClock.increment() | 521,434 ops/sec |
| fork() on 1,000-entry namespace | 1.59 ms (O(1)) |

---

## 15. Configuration Reference

### `NamespaceConfig` fields
```python
NamespaceConfig(
    name="my-ns",
    description="",
    default_conflict_strategy=ConflictStrategy.MERGE_STRUCTURAL,
    max_branches=50,
    max_entries_per_branch=10_000,
    enable_poisoning_detection=True,
    poisoning_threshold=0.85,       # cosine similarity (future use)
    enable_write_attribution=True,
    ttl_default_seconds=None,       # None = no expiry
    created_by="system",
)
```

### `AgentSkein` with all options
```python
from agentskein import AgentSkein, ConflictStrategy
from agentskein.storage.sqlite_backend import SQLiteBackend

async def my_embed(value) -> list[float]:
    ...  # call OpenAI / SentenceTransformers / etc.

async def my_llm(prompt: str) -> str:
    ...  # call Claude / GPT-4 / etc.

mesh = AgentSkein(
    agent_id       = "my-agent",
    namespace      = "my-task",
    branch         = "main",
    backend        = SQLiteBackend("data.db"),   # or RedisBackend / InMemoryBackend
    conflict_strategy = ConflictStrategy.MERGE_STRUCTURAL,
    lock_timeout_ms   = 3000,
    embedding_fn   = my_embed,   # populates entry.embedding on every write
    llm_merge_fn   = my_llm,     # used by MERGE_SEMANTIC strategy
)
```

---

## 16. Common Patterns

### Pattern 1: Parallel agents with unique keys (no conflicts expected)
```python
coordinator = AgentSkein("coord", "ns", backend=backend)
await coordinator.init()

for i in range(N):
    agent = AgentSkein(f"agent-{i}", "ns", backend=backend)
    branch = await agent.fork(f"branch-{i}")
    await branch.write(f"result-{i}", my_result)
    await branch.merge_to("main")

snapshot = await coordinator.snapshot()  # all N results present
```

### Pattern 2: Shared key with explicit conflict handling
```python
mesh = AgentSkein("agent", "ns", backend=backend,
                  conflict_strategy=ConflictStrategy.RAISE)
try:
    await mesh.write("shared-key", my_value)
except ConflictDetectedError as e:
    # e.conflict.entry_ours   = what we tried to write
    # e.conflict.entry_theirs = what's already stored
    # resolve manually and call mesh.write() again
    resolved = my_custom_merge(e.conflict)
    await mesh.write("shared-key", resolved)
```

### Pattern 3: Using context manager
```python
async with AgentSkein("agent", "ns") as mesh:
    await mesh.write("key", "value")
    result = await mesh.read("key")
# mesh.close() called automatically
```

### Pattern 4: LangGraph integration
```python
from agentskein.adapters.langgraph_adapter import AgentSkeinCheckpointer
from langgraph.graph import StateGraph

checkpointer = AgentSkeinCheckpointer(
    agent_id="orchestrator",
    namespace="my-workflow",
)
graph = StateGraph(MyState).compile(checkpointer=checkpointer)
result = await graph.ainvoke(state, config={"configurable": {"thread_id": "run-1"}})
```

---

## 17. Known Limitations

1. **Single-node Redlock**: Redis locking is on one node. Multi-node Redlock (5
   nodes) provides stronger fault tolerance. Planned for future.
2. **`embedding` dimensionality**: No fixed dimension. Mixing embeddings from
   different providers (e.g. dim=1536 and dim=768) in the same namespace will
   cause cosine similarity errors.
3. **No schema migration**: If `MemoryEntry` fields change between versions,
   old data in Redis/SQLite won't deserialise correctly.
4. **`MERGE_SEMANTIC` quality**: Depends entirely on the provided `llm_merge_fn`.
   No output validation or guardrails applied.
5. **`get_branch_entries()` on InMemory**: Only returns entries explicitly
   written to that branch — does not traverse the CoW parent chain. Use
   `get_entry(key)` for individual key lookups (which does traverse).

---

## 18. Environment Variables

| Variable | Default | Purpose |
|---|---|---|
| `REDIS_URL` | `redis://localhost:6379/0` | Redis connection string |
| `OPENAI_API_KEY` | — | For OpenAI embedding / LLM merge |
| `ANTHROPIC_API_KEY` | — | For Anthropic LLM merge |
| `PYTHONPATH` | — | Set to project root if maturin not compiled |

---

## 19. Technology Stack

| Component | Technology | Version |
|---|---|---|
| Primary language | Python | 3.12 |
| Merge engine | Rust via PyO3 | PyO3 0.21 |
| Build system | maturin | ≥1.5 |
| Data validation | Pydantic | v2 |
| Async | asyncio / anyio | — |
| Storage (prod) | Redis | 7.2 |
| Storage (offline) | SQLite via aiosqlite | — |
| Structured logging | structlog | 24.x |
| CLI | Click + Rich | 8.x / 13.x |
| Tests | pytest + pytest-asyncio | 8.x |
| IDs | ULID (ulid-py) | 1.1.0 |

---

## 20. File-by-File Quick Reference

| File | What it does |
|---|---|
| `agentskein/__init__.py` | Re-exports everything. Import from here. |
| `agentskein/client.py` | `AgentSkein` class. All write/read/fork/merge logic. |
| `agentskein/cli.py` | Click commands: watch, snapshot, branches, write. |
| `agentskein/protocol/types.py` | Core data types: MemoryEntry, VectorClock, Branch, Conflict, ConflictStrategy. |
| `agentskein/protocol/namespace.py` | NamespaceConfig + NamespaceState. |
| `agentskein/protocol/semantic_merge.py` | LLM merge prompt template + `semantic_merge()` function. |
| `agentskein/protocol/poisoning.py` | PoisoningDetector: injection patterns + storm detection. |
| `agentskein/storage/base.py` | StorageBackend Protocol (interface definition). |
| `agentskein/storage/redis_backend.py` | Redis backend: GET/SET/Lua lock. CoW fall-through. |
| `agentskein/storage/sqlite_backend.py` | SQLite backend: aiosqlite. CoW fall-through. [B9] |
| `agentskein/storage/memory_backend.py` | In-memory backend for tests. CoW fall-through. |
| `agentskein/adapters/langgraph_adapter.py` | AgentSkeinCheckpointer extends BaseCheckpointSaver. [B5] |
| `agentskein/adapters/crewai_adapter.py` | AgentSkeinStorage: save/search/reset. |
| `agentskein/adapters/autogen_adapter.py` | AgentSkeinStore: remember/recall/recall_all. |
| `core/src/lib.rs` | Rust: three_way_merge_json + PyO3 bindings. |
| `tests/unit/test_vector_clock.py` | 9 tests: causal ordering, concurrency, merge, immutability. |
| `tests/unit/test_poisoning.py` | 7 tests: injection patterns, storm detection. |
| `tests/unit/test_memory_backend.py` | 7 tests: InMemoryBackend + CoW [B3]. |
| `tests/unit/test_client_inmemory.py` | 16 tests: full client flow including B1/B3/B8/B11. |
| `tests/e2e/test_multi_agent_scenarios.py` | 5 E2E tests: parallel agents, branching, poisoning. |
| `comparison/run_all_benchmarks.py` | Runs all 5 benchmarks and writes comparison_report.txt. |
| `agentskein_paper.tex` | Full LaTeX academic paper. Compile: `pdflatex agentskein_paper.tex` × 2. |
| `agentskein_paper.pdf` | Compiled PDF (7 pages). |
| `setup_windows.ps1` | PowerShell: installs Python, Rust, Git, Docker, VSCode exts, venv. |
| `pyproject.toml` | maturin build backend. Use `maturin develop`, not `pip install -e .`. |
| `docker-compose.yml` | `docker compose up redis -d` starts Redis on port 6379. |
