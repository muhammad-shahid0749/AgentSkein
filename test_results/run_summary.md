# AgentSkein — Real-World Test Run Summary

**Scenarios:** 4    **Passed:** 4    **Failed:** 0

| Scenario | Verdict | Duration (s) | Headline |
|----------|---------|--------------|----------|
| `scenario_01_multi_writer_race` | PASS | 0.02 | Plain dict: 1/5 writes survived (4/5 lost silently, survivor=['agent-2']). |
| `scenario_02_disjoint_pipeline` | PASS | 0.00 | 3/3 perspectives preserved on main. |
| `scenario_03_branch_merge_strategies` | PASS | 0.00 | 5/5 strategies behave as documented. |
| `scenario_04_poisoning_defence` | PASS | 0.00 | Blocked 6/6 injection payloads, 0 false positives, storm alerts=5. |

## What each scenario tests

### `scenario_01_multi_writer_race`

**Claim:** AgentSkein detects concurrent writes via vector clocks and keeps an audit trail; naive backends silently lose 4 of 5 writers.

| Metric | Value |
|--------|-------|
| plain_dict_writes_surviving | 1 |
| naive_redis_writes_surviving | 1 |
| agentskein_writes_surviving | 5 |

Plain dict: 1/5 writes survived (4/5 lost silently, survivor=['agent-2']).

Naive Redis: 1/5 writes survived (4/5 lost silently, survivor=['agent-5']).

AgentSkein: 5/5 writers preserved as disjoint keys, shared 'market-size' resolved to chosen_by=['agent-5'], conflict detected via vector clocks.

### `scenario_02_disjoint_pipeline`

**Claim:** Disjoint top-level keys are unioned cleanly by the 3-way merge engine; all 3 writers' contributions are preserved on main.

| Metric | Value |
|--------|-------|
| perspectives_preserved | 3 |
| perspectives_expected | 3 |
| attribution_ok | True |

3/3 perspectives preserved on main.

### `scenario_03_branch_merge_strategies`

**Claim:** All 5 conflict strategies produce the documented outcome.

| Metric | Value |
|--------|-------|
| strategies_tested | 5 |
| strategies_passing | 5 |

5/5 strategies behave as documented.

### `scenario_04_poisoning_defence`

**Claim:** PoisoningDetector blocks injection payloads with severity=high and flags overwrite storms with severity=medium; benign writes pass through unflagged.

| Metric | Value |
|--------|-------|
| injections_blocked | 6 |
| injections_total | 6 |
| benign_false_positives | 0 |
| storm_alerts_observed | 5 |

Blocked 6/6 injection payloads, 0 false positives, storm alerts=5.
