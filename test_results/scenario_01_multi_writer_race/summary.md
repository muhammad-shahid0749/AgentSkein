# scenario_01_multi_writer_race — PASS

_Five agents race to write the same shared key 'market-size'. We compare plain dict / naive Redis / AgentSkein and count how many writers survive on the final state._

**Claim under test:** AgentSkein detects concurrent writes via vector clocks and keeps an audit trail; naive backends silently lose 4 of 5 writers.

**Verdict:** PASS

## Summary

Plain dict: 1/5 writes survived (4/5 lost silently, survivor=['agent-2']).

Naive Redis: 1/5 writes survived (4/5 lost silently, survivor=['agent-5']).

AgentSkein: 5/5 writers preserved as disjoint keys, shared 'market-size' resolved to chosen_by=['agent-5'], conflict detected via vector clocks.

## Metrics

| Metric | Value |
|--------|-------|
| plain_dict_writes_surviving | 1 |
| naive_redis_writes_surviving | 1 |
| agentskein_writes_surviving | 5 |
| agentskein_conflict_detected | True |
| agentskein_audit_trail | True |
| writers | 5 |

## Event timeline

Each event is one line in `events.jsonl`. First 50 shown here:

| t (s) | event | fields |
|-------|-------|--------|
| 0.000 | `scenario.start` | {"scenario": "scenario_01_multi_writer_race", "description": "Five agents race to write the same shared key 'market-size |
| 0.000 | `plain_dict.start` | {} |
| 0.001 | `plain_dict.write` | {"agent": "agent-3", "value": "$2.3B"} |
| 0.001 | `plain_dict.write` | {"agent": "agent-5", "value": "$2.6B"} |
| 0.002 | `plain_dict.write` | {"agent": "agent-4", "value": "$1.9B"} |
| 0.004 | `plain_dict.write` | {"agent": "agent-1", "value": "$2.1B"} |
| 0.005 | `plain_dict.write` | {"agent": "agent-2", "value": "$2.4B"} |
| 0.005 | `plain_dict.final` | {"value": "$2.4B", "survivors": ["agent-2"]} |
| 0.009 | `naive_redis.start` | {"url": "redis://redis:6379/0"} |
| 0.010 | `naive_redis.write` | {"agent": "agent-2", "value": "$2.4B"} |
| 0.012 | `naive_redis.write` | {"agent": "agent-4", "value": "$1.9B"} |
| 0.012 | `naive_redis.write` | {"agent": "agent-1", "value": "$2.1B"} |
| 0.014 | `naive_redis.write` | {"agent": "agent-3", "value": "$2.3B"} |
| 0.014 | `naive_redis.write` | {"agent": "agent-5", "value": "$2.6B"} |
| 0.014 | `naive_redis.final` | {"value": "$2.6B", "survivors": ["agent-5"]} |
| 0.014 | `agentskein.start` | {} |
| 0.016 | `agentskein.merge` | {"agent": "agent-2", "merged_keys": ["market-size", "by-agent-2"], "conflict_keys": []} |
| 0.017 | `agentskein.merge` | {"agent": "agent-4", "merged_keys": ["market-size", "by-agent-4"], "conflict_keys": []} |
| 0.018 | `agentskein.merge` | {"agent": "agent-1", "merged_keys": ["market-size", "by-agent-1"], "conflict_keys": []} |
| 0.019 | `agentskein.merge` | {"agent": "agent-3", "merged_keys": ["market-size", "by-agent-3"], "conflict_keys": []} |
| 0.020 | `agentskein.merge` | {"agent": "agent-5", "merged_keys": ["market-size", "by-agent-5"], "conflict_keys": []} |
| 0.020 | `agentskein.final` | {"market_size": {"estimate": "$2.6B", "chosen_by": "agent-5"}, "per_agent_keys_preserved": ["by-agent-2", "by-agent-4",  |
| 0.020 | `scenario.outcome` | {"passed": true, "summary": "Plain dict: 1/5 writes survived (4/5 lost silently, survivor=['agent-2']).\n\nNaive Redis:  |
| 0.020 | `scenario.end` | {"duration_s": 0.0199} |

## Files in this directory

- `events.jsonl` — one JSON object per event, full fidelity.
- `result.json`  — final outcome, metrics, verdict.
- `summary.md`   — this file.