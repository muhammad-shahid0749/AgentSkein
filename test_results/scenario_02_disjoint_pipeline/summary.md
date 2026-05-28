# scenario_02_disjoint_pipeline — PASS

_Three researcher agents each write a finding to a unique top-level key (analysis-by-popularity / analysis-by-activity / analysis-by-adoption) on their own branch, then merge to main._

**Claim under test:** Disjoint top-level keys are unioned cleanly by the 3-way merge engine; all 3 writers' contributions are preserved on main.

**Verdict:** PASS

## Summary

All 3 disjoint keys present on main: ['analysis-by-activity', 'analysis-by-adoption', 'analysis-by-popularity']. Missing: none. Attribution intact: True.

## Metrics

| Metric | Value |
|--------|-------|
| writers | 3 |
| perspectives_preserved | 3 |
| perspectives_expected | 3 |
| attribution_ok | True |
| total_keys_on_main | 3 |

## Event timeline

Each event is one line in `events.jsonl`. First 50 shown here:

| t (s) | event | fields |
|-------|-------|--------|
| 0.000 | `scenario.start` | {"scenario": "scenario_02_disjoint_pipeline", "description": "Three researcher agents each write a finding to a unique t |
| 0.000 | `researcher.write` | {"agent": "Researcher-1", "key": "analysis-by-popularity"} |
| 0.000 | `researcher.merge` | {"agent": "Researcher-1", "merged_keys": ["analysis-by-popularity"], "conflict_keys": []} |
| 0.001 | `researcher.write` | {"agent": "Researcher-2", "key": "analysis-by-activity"} |
| 0.001 | `researcher.merge` | {"agent": "Researcher-2", "merged_keys": ["analysis-by-activity"], "conflict_keys": []} |
| 0.001 | `researcher.write` | {"agent": "Researcher-3", "key": "analysis-by-adoption"} |
| 0.001 | `researcher.merge` | {"agent": "Researcher-3", "merged_keys": ["analysis-by-adoption"], "conflict_keys": []} |
| 0.001 | `verify.snapshot` | {"present_keys": ["analysis-by-activity", "analysis-by-adoption", "analysis-by-popularity"], "missing_keys": [], "attrib |
| 0.001 | `scenario.outcome` | {"passed": true, "summary": "All 3 disjoint keys present on main: ['analysis-by-activity', 'analysis-by-adoption', 'anal |
| 0.001 | `scenario.end` | {"duration_s": 0.0009} |

## Files in this directory

- `events.jsonl` — one JSON object per event, full fidelity.
- `result.json`  — final outcome, metrics, verdict.
- `summary.md`   — this file.