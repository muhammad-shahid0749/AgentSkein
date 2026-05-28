# scenario_03_branch_merge_strategies — PASS

_For each of the 5 conflict strategies, two agents write the same key on independent branches and merge back to main. We verify the documented outcome holds in every case._

**Claim under test:** All 5 conflict strategies produce the documented outcome.

**Verdict:** PASS

## Summary

- `last_write_wins` → final={'amount': 200, 'currency': 'USD', 'by': 'agent-b'} raised=False expectation_met=True
- `first_write_wins` → final={'amount': 100, 'currency': 'USD', 'by': 'agent-a'} raised=False expectation_met=True
- `merge_structural` → final={'amount': 200, 'currency': 'USD', 'by': 'agent-b'} raised=False expectation_met=True
- `merge_semantic` → final={'amount': 200, 'currency': 'USD', 'by': 'agent-b'} raised=False expectation_met=True
- `raise` → final={'amount': 100, 'currency': 'USD', 'by': 'agent-a'} raised=True expectation_met=True

## Metrics

| Metric | Value |
|--------|-------|
| strategies_tested | 5 |
| strategies_passing | 5 |

## Event timeline

Each event is one line in `events.jsonl`. First 50 shown here:

| t (s) | event | fields |
|-------|-------|--------|
| 0.000 | `scenario.start` | {"scenario": "scenario_03_branch_merge_strategies", "description": "For each of the 5 conflict strategies, two agents wr |
| 0.000 | `strategy.setup` | {"strategy": "last_write_wins", "branch_a_value": {"amount": 100, "currency": "USD", "by": "agent-a"}, "branch_b_value": |
| 0.001 | `strategy.merge_a_done` | {"strategy": "last_write_wins"} |
| 0.001 | `strategy.final` | {"strategy": "last_write_wins", "value": {"amount": 200, "currency": "USD", "by": "agent-b"}, "raised": false} |
| 0.001 | `strategy.setup` | {"strategy": "first_write_wins", "branch_a_value": {"amount": 100, "currency": "USD", "by": "agent-a"}, "branch_b_value" |
| 0.001 | `strategy.merge_a_done` | {"strategy": "first_write_wins"} |
| 0.001 | `strategy.final` | {"strategy": "first_write_wins", "value": {"amount": 100, "currency": "USD", "by": "agent-a"}, "raised": false} |
| 0.002 | `strategy.setup` | {"strategy": "merge_structural", "branch_a_value": {"amount": 100, "currency": "USD", "by": "agent-a"}, "branch_b_value" |
| 0.002 | `strategy.merge_a_done` | {"strategy": "merge_structural"} |
| 0.002 | `strategy.final` | {"strategy": "merge_structural", "value": {"amount": 200, "currency": "USD", "by": "agent-b"}, "raised": false} |
| 0.002 | `strategy.setup` | {"strategy": "merge_semantic", "branch_a_value": {"amount": 100, "currency": "USD", "by": "agent-a"}, "branch_b_value":  |
| 0.002 | `strategy.merge_a_done` | {"strategy": "merge_semantic"} |
| 0.002 | `strategy.final` | {"strategy": "merge_semantic", "value": {"amount": 200, "currency": "USD", "by": "agent-b"}, "raised": false} |
| 0.003 | `strategy.setup` | {"strategy": "raise", "branch_a_value": {"amount": 100, "currency": "USD", "by": "agent-a"}, "branch_b_value": {"amount" |
| 0.003 | `strategy.merge_a_done` | {"strategy": "raise"} |
| 0.003 | `strategy.conflict_raised` | {"strategy": "raise", "ours": {"amount": 200, "currency": "USD", "by": "agent-b"}, "theirs": {"amount": 100, "currency": |
| 0.003 | `strategy.final` | {"strategy": "raise", "value": {"amount": 100, "currency": "USD", "by": "agent-a"}, "raised": true} |
| 0.003 | `scenario.outcome` | {"passed": true, "summary": "- `last_write_wins` \u2192 final={'amount': 200, 'currency': 'USD', 'by': 'agent-b'} raised |
| 0.003 | `scenario.end` | {"duration_s": 0.0028} |

## Files in this directory

- `events.jsonl` — one JSON object per event, full fidelity.
- `result.json`  — final outcome, metrics, verdict.
- `summary.md`   — this file.