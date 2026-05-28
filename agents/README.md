# AgentSkein — Reference Multi-Agent Pipeline

This folder contains a working five-agent pipeline that exercises every feature
of the AgentSkein library against the live GitHub Search API. It is the canonical
"does this work?" demo for the project.

```text
Orchestrator
  Researcher-1  (POPULARITY - ranks by stars)
  Researcher-2  (ACTIVITY   - ranks by pushed_at)
  Researcher-3  (ADOPTION   - ranks by forks)
  Safety-Monitor (injection tests + storm test + repo-description scan)
        (all four run concurrently in Phase 1)
Analyst   (reads each researcher's branch -> builds the conflict-resolution proof)
Writer    (renders the seven-section intelligence report)
```

## How to run it

The pipeline talks to AgentSkein through the FastAPI HTTP server. Start the
server in one terminal and the orchestrator in another:

```bash
# Terminal 1 - boot the API server
python examples/n8n_api_server/server.py

# Terminal 2 - kick off the orchestrator
python agents/run_agents.py
```

The orchestrator finishes in roughly 4-40 seconds depending on GitHub API
latency. When it returns, `agents/ai_ecosystem_report.txt` is regenerated.

## What the pipeline demonstrates

Three concurrent-write patterns, all reported honestly in the final report:

| Pattern | Where it's exercised | What you see on `main` |
|---------|---------------------|------------------------|
| **A. Disjoint top-level keys** | Each researcher writes a unique key (`analysis-by-popularity` / `analysis-by-activity` / `analysis-by-adoption`) | All three keys present, full per-agent attribution - `3 / 3 perspectives preserved` |
| **B. Shared same-key writes**  | All three researchers write the same `verdict` key with disagreeing scalar fields | Conflict DETECTED via vector clocks, one survivor on `main`, `chosen_by` audit trail preserved |
| **C. Repo-key overlaps**        | When multiple researchers find the same repo (e.g. AutoGPT was found by all three) | Structural merge unions non-conflicting fields per repo |

This is the design point of the project: 3-way merge unions **disjoint** keys
losslessly; on **same-key** disagreement it detects + audits but does not
fabricate a union. Pick the pattern that matches the semantics you want.

## The seven-section report

`ai_ecosystem_report.txt` (~500 lines) is regenerated every run from the live
state in AgentSkein - no static text:

| Section | Content |
|---------|---------|
| 1 | **Executive summary** - verdict on the framework's claim |
| 2 | **Per-agent activity timeline** - every event with timestamps |
| 3 | **Conflict resolution analysis** - Patterns A, B, C pre-merge vs post-merge |
| 4 | **Research statistics** - live GitHub data |
| 5 | **Safety analysis** - injection / storm / scan results |
| 6 | **Verification metrics** - aggregate event counts |
| 7 | **Efficiency analysis** - phase timing, concurrency speedup, throughput |

## Files

| File | Role |
|------|------|
| `run_agents.py`            | Entry point - instantiates the orchestrator |
| `orchestrator_agent.py`    | Coordinates the three phases, logs phase transitions |
| `researcher_agent.py`      | One of three researchers; pulls GitHub data, writes disjoint + shared keys |
| `analyst_agent.py`         | Reads each researcher's branch to build the truthful conflict story |
| `safety_agent.py`          | Injection tests + storm test + GitHub-description scan |
| `writer_agent.py`          | Renders the seven-section report from AgentSkein state |
| `base_agent.py`            | Shared HTTP client, activity logger, flush helpers |
| `ai_ecosystem_report.txt`  | Regenerated each run - the canonical proof artefact |

## Activity logging

Every agent records timestamped events (step #, ms offset, event name,
payload) and flushes the log to AgentSkein under `activity-{agent_id}`
before its branch merges. The writer reads these verbatim into Section 2,
so what you see in the report is exactly what the agents did - no
reconstruction.

## Verifying the claim

After a run, the key line in Section 1 is:

```text
Pattern A - disjoint top-level keys ...
           3 of 3 researcher perspectives preserved on main.
           -> [PASS - zero data loss across 3 concurrent writers]
```

If you see anything other than `3 of 3` and `PASS`, look at Section 3a's
per-key dump - it shows for each disjoint key whether it was present on
the researcher's branch, present on `main`, and whether the `by_agent`
attribution matches. That's the verifiable end-to-end check.

## Customising the pipeline

The simplest knobs:

- **Reduce GitHub round trips** - edit `researcher_agent.py` and change
  `per_page=10` to a smaller number; the pipeline will finish faster.
- **Swap the backend** - by default the HTTP server uses `InMemoryBackend`.
  Set `REDIS_URL=redis://localhost:6379/0` before starting the server to use
  Redis instead. (Variable name matches the one read by
  `examples/n8n_api_server/server.py`.)
- **Add another researcher** - give it a new metric and a unique
  `analysis-by-{metric}` key, then add it to the `asyncio.gather(...)` call
  in `orchestrator_agent.py`. No other code changes required.
- **Bring your own LLM merge** - pass an `llm_merge_fn` to the
  `AgentSkein` constructor in the server and switch `verdict`'s strategy
  to `merge_semantic` to demonstrate Pattern B with an LLM.

See [`../AGENTS_INTEGRATION_GUIDE.md`](../AGENTS_INTEGRATION_GUIDE.md) for
how to plug AgentSkein into your own agents (LangGraph / CrewAI / AutoGen
/ raw HTTP / n8n).
