# AgentSkein — Real-World Agent Integration Guide

> **What this library does.** AgentSkein is the first open-source library to
> bring Git-style three-way merge to LLM agent memory. It gives a pool of
> concurrent agents (LangGraph / CrewAI / AutoGen / n8n / raw API) a shared
> key-value store with vector-clock conflict detection, branching, and a
> 3-way merge engine — all behind a small HTTP API so any orchestrator can use it.
>
> **What this guide covers.** How to plug AgentSkein into your existing agent
> stack, which write patterns actually preserve every agent's contribution
> (and which ones only *detect* the conflict), how to pick a backend, and how
> to keep the server running in production.

---

## Visual overview (look at these first)

Three short diagrams; read them in order and the rest of this guide makes sense.

1. **Where AgentSkein sits in your stack** — [`docs/integration-architecture.svg`](docs/integration-architecture.svg).
   Your framework on top, AgentSkein in the middle (in-process import OR HTTP),
   storage backend at the bottom.
2. **The three write patterns** — [`docs/three-patterns.svg`](docs/three-patterns.svg).
   Disjoint keys (Pattern A — every writer kept), shared same-key writes
   (Pattern B — detect + audit, single survivor), and accidental overlaps
   (Pattern C — auto-unioned). Pick A unless you have a reason not to.
3. **n8n HTTP workflow** — [`docs/n8n-workflow.svg`](docs/n8n-workflow.svg).
   Three HTTP Request nodes, the exact JSON body to POST, and what comes back.

Want the full diagram set with copy-paste recipes per stack? Open
[`docs/README.md`](docs/README.md).

---

## The Big Picture: What Problem Does This Solve in Practice?

Imagine you build an n8n workflow where three AI agents run in parallel:

```
Agent 1 (Researcher)  →  writes  market-size = $2.1B    →  shared memory
Agent 2 (Analyst)     →  writes  market-size = $2.4B    →  shared memory   ← CONFLICT
Agent 3 (Writer)      →  reads   market-size = ???       ←  shared memory
```

**Without AgentSkein:** Agent 2 silently overwrites Agent 1. Agent 3 reads
whichever value happened to land last. You have no idea this happened, your
report contains wrong data, and you never know why.

**With AgentSkein:** The framework gives you two honest paths:

1. **Disjoint-key pattern** *(the recommended pattern when you want to
   preserve every agent's view)*. Each agent writes its contribution to a
   unique top-level key — for example `market-size-from-researcher`,
   `market-size-from-analyst`. The 3-way merge engine cleanly unions these
   onto `main` because the keys are disjoint. Agent 3 sees BOTH numbers,
   attributed to the agent that produced each.

2. **Same-key pattern** *(the right pattern when you want a single value with
   conflict detection)*. Both agents write the same `market-size` key. The
   merge engine **detects** the conflict via vector clocks and records full
   audit trail (`chosen_by`, vector clocks). With `merge_structural` you get
   one survivor; with `merge_semantic` you route the disagreement to an LLM;
   with `raise` you get a 409 you can handle in your workflow.

Either way the conflict is no longer silent, attribution is preserved, and a
poisoning detector blocks any LLM that tries to inject
`"Ignore all previous instructions"` into shared memory.

---

## How AgentSkein Fits Into an AI Agent System

AgentSkein is a **shared memory layer** that sits between your agents and
storage. Think of it exactly like a Git repository — but for agent state
instead of code files.

```
┌─────────────────────────────────────────────────────────────┐
│                     YOUR WORKFLOW TOOL                       │
│                                                              │
│   n8n  /  LangGraph  /  CrewAI  /  AutoGen  /  Custom       │
└────────────────────────┬────────────────────────────────────┘
                         │  read / write / fork / merge
┌────────────────────────▼────────────────────────────────────┐
│                    AGENTSKEIN LAYER                          │
│                                                              │
│   • Conflict detection (vector clocks)                       │
│   • Three-way merge (combines non-conflicting changes)       │
│   • Branching (agents work in isolation, merge when done)    │
│   • Attribution (every write knows which agent wrote it)     │
│   • Poisoning detection (blocks prompt injection attacks)    │
└────────────────────────┬────────────────────────────────────┘
                         │
┌────────────────────────▼────────────────────────────────────┐
│                      STORAGE                                 │
│                                                              │
│   Redis (production)  •  SQLite (offline)  •  InMemory      │ 
└─────────────────────────────────────────────────────────────┘
```

---



## The Two Concurrent-Write Patterns You Will Actually Use

This is the single most important section of this guide. Pick the right pattern
for your situation; the framework's behaviour follows from that choice.

### Pattern A — Disjoint Top-Level Keys  *(use this for "preserve every writer")*

Every agent writes to a **unique top-level key**. The 3-way merge engine
unions these cleanly because there is nothing to conflict on at the key level.

```text
researcher-1 writes  →  analysis-by-popularity   = {...}
researcher-2 writes  →  analysis-by-activity     = {...}
researcher-3 writes  →  analysis-by-adoption     = {...}

After all three merge:
main = {
  analysis-by-popularity: {... from researcher-1, attribution preserved},
  analysis-by-activity:   {... from researcher-2, attribution preserved},
  analysis-by-adoption:   {... from researcher-3, attribution preserved},
}
```

This is the pattern verified end-to-end in `agents/run_agents.py`. In the
reference run, **3 of 3 perspectives were preserved on `main`**, attributed
to the originating agent via a `by_agent` field inside the value.

**Use this when:** you want every agent's view kept verbatim and you can
choose distinct keys at write time.

### Pattern B — Shared Same-Key Writes  *(use this for "detect, then decide")*

Every agent writes to the **same** key, with a value whose fields disagree.
The 3-way merge engine **detects** the concurrency via vector clocks and
records full attribution; what it *cannot* do is fabricate a union when both
writers disagree on the same scalar.

```text
researcher-1 writes  →  verdict = {winner: "A", chosen_by: "r1", ...}
researcher-2 writes  →  verdict = {winner: "B", chosen_by: "r2", ...}

After both merge with strategy=merge_structural:
main.verdict = {winner: "B", chosen_by: "r2", ...}   ← one survivor
                                                       audit trail preserved
                                                       conflict was DETECTED
```

**Use this when:** you want a single value at the end of the day and you have
a clear policy for resolving disagreement. Choose the strategy:

| Strategy            | What happens on a same-key conflict                          |
|---------------------|--------------------------------------------------------------|
| `merge_structural`  | Single survivor per scalar field; non-conflicting fields union; audit trail kept |
| `merge_semantic`    | Conflict routed to an LLM callable that returns a merged value |
| `last_write_wins`   | Latest writer wins; no merging                               |
| `first_write_wins`  | Earliest writer wins (conservative facts)                    |
| `raise`             | Conflict surfaces as HTTP 409; your orchestrator handles it  |

### The Single Rule

> **If you need every writer's view preserved, give each writer its own
> top-level key.** If you only need one value at the end with a clean audit
> trail, share the key and pick a strategy. Both are first-class patterns.

---

## Part 1: n8n Integration (Your Main Use Case)

### Why n8n Needs a REST API Bridge

n8n is a visual workflow builder that runs Node.js. AgentSkein is a Python
library. They cannot talk to each other directly. The solution is to run
AgentSkein as a small HTTP server (FastAPI), and have n8n call it using the
standard **HTTP Request** node.

```
n8n Workflow
    [HTTP Request node]  →  POST /namespace/my-task/write/result
                         →  GET  /namespace/my-task/read/result
                         →  POST /namespace/my-task/merge
                         ←  JSON responses
                    AgentSkein FastAPI Server (localhost:8765)
                         ↕
                    Redis / SQLite / InMemory
```

### Step 1: Start the AgentSkein API Server

Open a terminal in the `agentskein/` folder with your venv activated:

```powershell
# Windows
.\.venv\Scripts\Activate.ps1
python examples\n8n_api_server\server.py
```

You will see:
```
  AgentSkein API Server starting on http://0.0.0.0:8765
  Swagger UI: http://localhost:8765/docs
  ReDoc:      http://localhost:8765/redoc
```

Open `http://localhost:8765/docs` in your browser — you will see the
interactive API documentation where you can test every endpoint.

**Backend auto-selection:**
- If Redis is running (`docker compose up redis -d`) → uses Redis (persistent)
- If Redis is not running → uses InMemory (data lost on restart)
- To use SQLite: set `SQLITE_PATH=./data.db` environment variable

### Step 2: Build the n8n Workflow

Here is a complete n8n workflow for a multi-agent research task. Each numbered
item is one n8n node.

---

#### Workflow: "Parallel Research with Shared Memory"

**Goal:** Three AI agents research different topics in parallel, write their
findings to AgentSkein, then a fourth agent reads the combined result.

---

**Node 1 — Trigger (Manual or Schedule)**
```
Type: Manual Trigger  (or Cron for scheduled runs)
No configuration needed.
```

---

**Node 2 — Init Namespace**
```
Type: HTTP Request
Method: POST
URL: http://localhost:8765/namespace/market-research/init
Body (JSON):
  {
    "agent_id": "orchestrator",
    "description": "Market research task started by n8n"
  }
```

---

**Node 3 — Split Into Parallel Branches**
```
Type: Split In Batches  (or use parallel execution)
Batch Size: 1
Items:
  [
    { "agent": "researcher-1", "topic": "AI memory tools" },
    { "agent": "researcher-2", "topic": "Vector databases" },
    { "agent": "researcher-3", "topic": "Multi-agent frameworks" }
  ]
```

---

**Node 4 — Fork Branch for Each Agent**
```
Type: HTTP Request
Method: POST
URL: http://localhost:8765/namespace/market-research/fork
Body (JSON):
  {
    "agent_id": "{{ $json.agent }}",
    "branch_name": "branch/{{ $json.agent }}",
    "from_branch": "main"
  }
```

---

**Node 5 — Call OpenAI / Claude for Each Agent**
```
Type: OpenAI node (or HTTP Request to Anthropic)
Prompt: "Research the topic: {{ $json.topic }}. Return a JSON object with
         keys: summary, market_size, key_players, gap_analysis"
Model: gpt-4o  (or claude-opus-4-6)
```

---

**Node 6 — Poison Check (Safety Gate)**

Before writing LLM output to shared memory, check it for injection attacks:

```
Type: HTTP Request
Method: POST
URL: http://localhost:8765/detect-poisoning
Body (JSON):
  {
    "agent_id": "{{ $json.agent }}",
    "namespace": "market-research",
    "key": "finding-{{ $json.agent }}",
    "value": {{ $json.llm_output }}
  }

Add IF node after:
  Condition: {{ $json.safe }} equals true
  True branch  → proceed to write
  False branch → send alert, stop this branch
```

---

**Node 7 — Write Finding to Agent's Branch**
```
Type: HTTP Request
Method: POST
URL: http://localhost:8765/namespace/market-research/write/finding-{{ $json.agent }}
Body (JSON):
  {
    "agent_id": "{{ $json.agent }}",
    "value": {{ $json.llm_output }},
    "branch": "branch/{{ $json.agent }}",
    "conflict_strategy": "merge_structural"
  }
```

---

**Node 8 — Merge Branch to Main**

After all agents finish (use a "Wait" or "Merge" node to synchronise):

```
Type: HTTP Request
Method: POST
URL: http://localhost:8765/namespace/market-research/merge
Body (JSON):
  {
    "agent_id": "{{ $json.agent }}",
    "from_branch": "branch/{{ $json.agent }}",
    "to_branch": "main",
    "conflict_strategy": "merge_structural"
  }
```

---

**Node 9 — Read Combined Result**

Now read everything that all agents wrote:

```
Type: HTTP Request
Method: GET
URL: http://localhost:8765/namespace/market-research/snapshot
    ?agent_id=orchestrator&branch=main

Returns:
  {
    "namespace": "market-research",
    "branch": "main",
    "count": 3,
    "data": {
      "finding-researcher-1": { "summary": "...", "market_size": "..." },
      "finding-researcher-2": { "summary": "...", "market_size": "..." },
      "finding-researcher-3": { "summary": "...", "market_size": "..." }
    }
  }
```

---

**Node 10 — Final Synthesis Agent**

Pass the combined data to a final LLM call for synthesis:

```
Type: OpenAI node
Prompt: "Here are research findings from 3 agents:
         {{ JSON.stringify($json.data) }}
         Write a 3-paragraph executive summary."
```

---

### Complete API Reference for n8n

All endpoints return JSON. Base URL: `http://localhost:8765`

| n8n Action | Method | URL | Key Body Fields |
|---|---|---|---|
| Start a task | POST | `/namespace/{task}/init` | `agent_id` |
| Agent writes a result | POST | `/namespace/{task}/write/{key}` | `agent_id`, `value`, `branch` |
| Agent reads a result | GET | `/namespace/{task}/read/{key}` | `?agent_id=x` |
| Read everything | GET | `/namespace/{task}/snapshot` | `?branch=main` |
| Fork isolated branch | POST | `/namespace/{task}/fork` | `agent_id`, `branch_name` |
| Merge back to main | POST | `/namespace/{task}/merge` | `from_branch`, `to_branch` |
| Check for injection | POST | `/detect-poisoning` | `agent_id`, `value` |
| Server health | GET | `/health` | — |
| Interactive docs | GET | `/docs` | — |

### Conflict Strategy Reference for n8n

Set `conflict_strategy` in the write body:

| Value | What happens when 2 agents write the same key |
|---|---|
| `merge_structural` | Auto-merges dict fields. Agent A adds `role`, Agent B adds `dept` → result has both. **(Recommended)** |
| `last_write_wins` | Second agent's value replaces first. Simple. |
| `first_write_wins` | First value is preserved. Good for "first claim wins" logic. |
| `merge_semantic` | Sends both versions to an LLM to produce a merged text. |
| `raise` | Returns HTTP 409 Conflict — your n8n workflow handles it manually. |

---

## Part 2: LangGraph Integration (Python)

LangGraph is the most popular framework for building stateful agent graphs.
AgentSkein replaces LangGraph's built-in `MemorySaver`, giving your graphs
cross-process, conflict-aware memory.

### Basic Setup
```python
from agentskein.adapters.langgraph_adapter import AgentSkeinCheckpointer
from langgraph.graph import StateGraph, END
from typing import TypedDict

# Replace this:  checkpointer = MemorySaver()
# With this:
checkpointer = AgentSkeinCheckpointer(
    agent_id  = "my-graph",
    namespace = "my-workflow",
    redis_url = "redis://localhost:6379/0",
    conflict_strategy = "merge_structural",  # auto-merges state conflicts
)

class AgentState(TypedDict):
    messages: list
    findings: dict
    status: str

graph = (
    StateGraph(AgentState)
    .add_node("researcher", researcher_node)
    .add_node("writer",     writer_node)
    .add_edge("researcher", "writer")
    .add_edge("writer", END)
    .set_entry_point("researcher")
    .compile(checkpointer=checkpointer)
)

# Every graph.invoke() is now checkpointed to AgentSkein
# Resume a paused run:
config = {"configurable": {"thread_id": "run-42"}}
result = await graph.ainvoke(initial_state, config=config)
```

### Real-World Pattern: Multi-Agent Graph with Shared Memory

```python
from agentskein import AgentSkein, ConflictStrategy
from agentskein.storage.redis_backend import RedisBackend

shared_backend = RedisBackend("redis://localhost:6379/0")

# Each sub-agent in your LangGraph graph gets its own AgentSkein
async def researcher_node(state, config):
    agent_id  = config["configurable"]["agent_id"]
    namespace = config["configurable"]["namespace"]

    mesh = AgentSkein(agent_id, namespace, backend=shared_backend)
    await mesh.init()

    # Write findings — conflicts with other researchers auto-merged
    await mesh.write("findings", {
        "market_size":  "$2.1B",
        "key_players":  ["mem0", "Zep"],
        "gap":          "no multi-writer support",
    })

    # Read what other agents have written
    other_findings = await mesh.read("findings")
    return {**state, "findings": other_findings}
```

### When to Use LangGraph vs. n8n
- **LangGraph**: When all your agents are Python functions in the same codebase.
  Best for tightly-coupled agent logic with complex state transitions.
- **n8n**: When you want a visual workflow, or when different agents are in
  different services / languages / tools.

---

## Part 3: CrewAI Integration (Python)

CrewAI is a popular framework for role-based AI teams. AgentSkein replaces
CrewAI's default memory stores with conflict-aware shared memory.

```python
from agentskein.adapters.crewai_adapter import AgentSkeinStorage

# Create one storage instance shared by all crew members
storage = AgentSkeinStorage(
    namespace         = "market-research-crew",
    redis_url         = "redis://localhost:6379/0",
    conflict_strategy = ConflictStrategy.MERGE_STRUCTURAL,
)

# Each crew member saves to it with their own agent_id
await storage.save("researcher", "market-size", {"value": "$2.1B"})
await storage.save("analyst",    "market-size", {"value": "$2.4B"})  # conflict!
# → auto-merged: no data loss

# Search across all saved data
results = await storage.search("writer", "market", limit=5)
# Returns: [{"key": "market-size", "value": {...}}, ...]

# Full integration with a CrewAI Crew:
from crewai import Agent, Task, Crew

researcher = Agent(
    role="Market Researcher",
    goal="Find market sizing data",
    backstory="Expert in AI market research",
    verbose=True
)

task = Task(
    description="Research the AI memory tools market size",
    expected_output="A JSON with market_size and key_players",
    agent=researcher
)

# Crew saves all outputs to AgentSkein automatically
crew = Crew(agents=[researcher], tasks=[task], verbose=True)
result = crew.kickoff()

# Read what the crew wrote
snap = await storage.search("orchestrator", "market")
```

---

## Part 4: AutoGen Integration (Python)

AutoGen is Microsoft's multi-agent conversation framework. AgentSkein gives
AutoGen agents a shared, persistent, conflict-aware memory store.

```python
import autogen
from agentskein.adapters.autogen_adapter import AgentSkeinStore

# One shared store for the whole team
store = AgentSkeinStore(
    namespace = "autogen-project",
    redis_url = "redis://localhost:6379/0",
)

llm_config = {"model": "gpt-4o", "api_key": "your-key"}

user_proxy    = autogen.UserProxyAgent("user_proxy", human_input_mode="NEVER")
researcher    = autogen.AssistantAgent("researcher", llm_config=llm_config)
code_executor = autogen.AssistantAgent("code_executor", llm_config=llm_config)

# Agents write to shared memory during conversation
async def save_result(agent_name, key, value):
    await store.remember(agent_name, key, value)

async def load_result(agent_name, key):
    return await store.recall(agent_name, key)

# After a conversation, read back everything
all_facts = await store.recall_all("researcher")
```

---

## Part 5: Raw API (OpenAI / Claude / Any LLM)

No framework needed. Use AgentSkein directly with any LLM API.

```python
import asyncio
import anthropic
from agentskein import AgentSkein, ConflictStrategy
from agentskein.storage.sqlite_backend import SQLiteBackend

client = anthropic.Anthropic()

async def run_research_agent(agent_name: str, topic: str, shared_mesh: AgentSkein):
    """One research agent — runs independently."""

    # Fork a private branch to work in isolation
    my_branch = await shared_mesh.fork(f"branch/{agent_name}")

    # Call the LLM
    response = client.messages.create(
        model   = "claude-opus-4-6",
        max_tokens = 1024,
        messages = [{"role": "user",
                     "content": f"Research this topic and return JSON: {topic}"}]
    )
    result = response.content[0].text

    # Write to private branch — no conflict possible yet
    await my_branch.write("finding", {"topic": topic, "result": result})

    # Merge to main — conflict resolution happens here
    summary = await my_branch.merge_to("main")
    print(f"{agent_name}: merged {len(summary['merged_keys'])} keys, "
          f"{len(summary['conflict_keys'])} conflicts")

async def main():
    # Shared SQLite backend — works offline, no Redis needed
    backend = SQLiteBackend("research_results.db")
    shared  = AgentSkein("orchestrator", "research",
                          backend=backend,
                          conflict_strategy=ConflictStrategy.MERGE_STRUCTURAL)
    await shared.init()

    # Run 3 agents in parallel
    topics = [
        ("researcher-1", "AI memory tools market size 2025"),
        ("researcher-2", "Top multi-agent frameworks comparison"),
        ("researcher-3", "Vector database landscape"),
    ]
    await asyncio.gather(*[
        run_research_agent(name, topic, shared)
        for name, topic in topics
    ])

    # Read combined results
    snapshot = await shared.snapshot()
    print(f"\nAll findings ({len(snapshot)} keys):")
    for key, value in snapshot.items():
        print(f"  {key}: {str(value)[:80]}")

asyncio.run(main())
```

---

## Part 6: Architecture Patterns

### Pattern 1: Hub and Spoke (Most Common in n8n)

```
                    [n8n Orchestrator Node]
                           │
               ┌───────────┼───────────┐
               │           │           │
          [Agent 1]   [Agent 2]   [Agent 3]
               │           │           │
          fork("A")   fork("B")   fork("C")
               │           │           │
          write(...)  write(...)  write(...)
               │           │           │
               └─────merge("main")─────┘
                           │
               [Read final result from main]
```

Each agent works in its own branch. Merging to main is the synchronisation
point. Conflicts are auto-resolved. The orchestrator reads a clean, merged
result.

### Pattern 2: Pipeline (Sequential Agents)

```
[Agent 1: Researcher] → write("raw-data") → main
         ↓
[Agent 2: Analyst]    → read("raw-data") → write("analysis") → main
         ↓
[Agent 3: Writer]     → read("analysis") → write("report") → main
         ↓
[Final Report]        → read("report")
```

Sequential agents read each other's output causally — no conflicts possible
because each agent reads before writing. Vector clocks guarantee this.

### Pattern 3: Competing Agents (Let the Best Win)

Both agents write the **same** key with different proposed answers and you
let the framework pick:

```
[Agent A] → fork("A") → write("answer", solution_A)
[Agent B] → fork("B") → write("answer", solution_B)

Option 1 — RAISE on conflict, let an LLM judge:
  → merge both with conflict_strategy="raise"
  → n8n IF node: on HTTP 409, call a "Judge Agent" to pick the winner
  → write the winning answer to main

Option 2 — Auto-resolve textually with an LLM merge callable:
  → merge both with conflict_strategy="merge_semantic"
  → AgentSkein calls your llm_merge_fn(prompt) → merged text

Option 3 — Auto-resolve with a fixed policy (latest wins):
  → merge both with conflict_strategy="last_write_wins"
```

If instead you want to **keep both answers** without picking, use
Pattern A (disjoint keys) and write to `answer-from-A` / `answer-from-B`.

### Pattern 4: Checkpoint and Resume

```
[Long-running workflow starts]
    → write("progress", {"step": 1, "done": ["research"]})
    → write("progress", {"step": 2, "done": ["research","analysis"]})

[Workflow crashes at step 3]

[Restart]
    → read("progress") → {"step": 2, "done": [...]}
    → resume from step 3 automatically
```

---

## Part 7: Choosing the Right Backend

| Scenario | Backend | How to Configure |
|---|---|---|
| Local development / testing | InMemoryBackend | Default if Redis is off |
| n8n on your laptop, no Docker | SQLiteBackend | `SQLITE_PATH=./data.db` |
| Production n8n on a server | RedisBackend | `docker compose up redis -d` |
| Multiple n8n instances sharing memory | RedisBackend | All point to same Redis URL |
| Offline / air-gapped environment | SQLiteBackend | No internet needed |
| CI/CD pipeline tests | InMemoryBackend | Fastest, no setup |

---

## Part 8: Choosing the Right Conflict Strategy

This is the most important decision. Use this decision tree:

```
What are your agents writing?
│
├── You want EVERY writer's contribution preserved on main
│   → Use the DISJOINT-KEYS pattern: each writer picks a unique top-level key
│     (e.g. `result-from-A`, `result-from-B`). merge_structural will union them.
│     This is the pattern that actually preserves all perspectives.
│
├── Structured dicts that share keys but disagree on fields
│   Example: A writes {role: "researcher"}, B writes {role: "writer"}
│   → Use: merge_structural — non-overlapping fields union, conflicting
│     scalar fields fall back to one survivor (audit trail preserved).
│
├── Free text (summaries, paragraphs, descriptions)
│   Example: Agent A writes one summary, Agent B writes a different summary
│   → Use: merge_semantic  (requires LLM callable)
│
├── Simple scalar values (numbers, strings) where latest is correct
│   Example: status, timestamp, last-seen
│   → Use: last_write_wins
│
├── Facts that should never be changed once written
│   Example: original task definition, immutable config
│   → Use: first_write_wins
│
└── Critical data where you must handle conflicts manually
    Example: financial transactions, irreversible actions
    → Use: raise  (your workflow catches HTTP 409 and decides)
```

---

## Part 9: Keeping the API Server Running

### Development (your laptop)
```powershell
# Simple — auto-reloads on code changes
python examples\n8n_api_server\server.py
```

### Production (Windows Service or server)
```powershell
# Install as a Windows Service using NSSM (Non-Sucking Service Manager)
# Download NSSM from https://nssm.cc/

nssm install AgentSkeinAPI
# Set path: <path-to-agentskein>\.venv\Scripts\python.exe
# Set args: examples\n8n_api_server\server.py
# Set working dir: <path-to-agentskein>

nssm start AgentSkeinAPI
```

### Docker (recommended for production)
```yaml
# Add to your docker-compose.yml:
services:
  agentskein-api:
    build: .
    command: python examples/n8n_api_server/server.py
    ports:
      - "8765:8765"
    environment:
      - REDIS_URL=redis://redis:6379/0
    depends_on:
      redis:
        condition: service_healthy
```

---

## Part 10: Complete Working Example (n8n + Python)

Here is the simplest possible end-to-end test you can run right now to prove
everything works together.

**Terminal 1 — Start the server:**
```powershell
cd "<path-to-agentskein>"
.\.venv\Scripts\Activate.ps1
python examples\n8n_api_server\server.py
```

**Terminal 2 — Simulate n8n with curl (or use Postman / Insomnia):**
```powershell
# 1. Init namespace
curl -X POST http://localhost:8765/namespace/test-task/init `
     -H "Content-Type: application/json" `
     -d '{"agent_id": "orchestrator"}'

# 2. Agent 1 writes a finding
curl -X POST http://localhost:8765/namespace/test-task/write/finding-1 `
     -H "Content-Type: application/json" `
     -d '{"agent_id": "agent-1", "value": {"result": "CRDT works well"}}'

# 3. Agent 2 writes a different finding
curl -X POST http://localhost:8765/namespace/test-task/write/finding-2 `
     -H "Content-Type: application/json" `
     -d '{"agent_id": "agent-2", "value": {"result": "Redis is fast"}}'

# 4. Read everything (both findings visible)
curl http://localhost:8765/namespace/test-task/snapshot

# 5. Check the interactive docs
# Open in browser: http://localhost:8765/docs
```

**In n8n:** Replace the curl commands with HTTP Request nodes pointing to the
same URLs. The workflow is identical — n8n just provides the visual interface
and scheduling.

---

## Summary

**Headline:** AgentSkein is the first open-source library to bring
Git-style three-way merge to LLM agent memory. Pick **disjoint keys**
when you want every writer preserved; pick **shared keys** when you want
one survivor with a clean audit trail.

**Reference implementation:** `agents/run_agents.py` runs five real agents
(Orchestrator + 3 Researchers + Safety + Analyst + Writer) against the
live GitHub API and produces a 6-section report in
`agents/ai_ecosystem_report.txt` that includes per-agent activity
timelines and pipeline efficiency metrics.

| Tool | Integration Method | Effort |
|---|---|---|
| **n8n** | HTTP Request nodes → AgentSkein REST API | Low — just configure URLs |
| **LangGraph** | `AgentSkeinCheckpointer` class | Low — one line replaces MemorySaver |
| **CrewAI** | `AgentSkeinStorage` class | Low — pass to Crew constructor |
| **AutoGen** | `AgentSkeinStore` class | Low — call remember/recall directly |
| **Raw Python** | `AgentSkein` class directly | Lowest — import and use |
| **Any HTTP tool** | REST API server | Low — curl / Postman / any client |

The REST API (`examples/n8n_api_server/server.py`) is the universal bridge.
Any tool that can make an HTTP request — n8n, Make, Zapier, a mobile app, a
bash script — can use AgentSkein for conflict-safe shared agent memory.
