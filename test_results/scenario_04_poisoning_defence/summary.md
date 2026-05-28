# scenario_04_poisoning_defence — PASS

_We push 6 injection payloads + 3 benign writes through PoisoningDetector and then trigger an overwrite storm. We verify the detector flags exactly the adversarial inputs._

**Claim under test:** PoisoningDetector blocks injection payloads with severity=high and flags overwrite storms with severity=medium; benign writes pass through unflagged.

**Verdict:** PASS

## Summary

Injection wave: 6/6 blocked. Benign wave: 0 false positives (should be 0). Storm wave: 5 medium alerts (≥1 expected).

## Metrics

| Metric | Value |
|--------|-------|
| injections_blocked | 6 |
| injections_total | 6 |
| benign_false_positives | 0 |
| benign_total | 3 |
| storm_alerts_observed | 5 |

## Event timeline

Each event is one line in `events.jsonl`. First 50 shown here:

| t (s) | event | fields |
|-------|-------|--------|
| 0.000 | `scenario.start` | {"scenario": "scenario_04_poisoning_defence", "description": "We push 6 injection payloads + 3 benign writes through Poi |
| 0.000 | `wave1.injection` | {"key": "inj.1", "blocked": true, "alert_count": 1, "first_alert_reason": "Prompt injection pattern detected: ignore\\s+ |
| 0.000 | `wave1.injection` | {"key": "inj.2", "blocked": true, "alert_count": 2, "first_alert_reason": "Prompt injection pattern detected: disregard\ |
| 0.000 | `wave1.injection` | {"key": "inj.3", "blocked": true, "alert_count": 1, "first_alert_reason": "Prompt injection pattern detected: <\\|system |
| 0.000 | `wave1.injection` | {"key": "inj.4", "blocked": true, "alert_count": 1, "first_alert_reason": "Prompt injection pattern detected: \\[INST\\] |
| 0.001 | `wave1.injection` | {"key": "inj.5", "blocked": true, "alert_count": 1, "first_alert_reason": "Prompt injection pattern detected: you\\s+are |
| 0.001 | `wave1.injection` | {"key": "inj.6", "blocked": true, "alert_count": 1, "first_alert_reason": "Prompt injection pattern detected: ###\\s*Hum |
| 0.001 | `wave1.benign` | {"key": "ok.1", "flagged": false, "alert_count": 0} |
| 0.001 | `wave1.benign` | {"key": "ok.2", "flagged": false, "alert_count": 0} |
| 0.001 | `wave1.benign` | {"key": "ok.3", "flagged": false, "alert_count": 0} |
| 0.001 | `wave2.storm.start` | {"threshold": 20} |
| 0.001 | `wave2.storm.complete` | {"storm_alerts_seen": 5} |
| 0.001 | `scenario.outcome` | {"passed": true, "summary": "Injection wave: 6/6 blocked. Benign wave: 0 false positives (should be 0). Storm wave: 5 me |
| 0.001 | `scenario.end` | {"duration_s": 0.0009} |

## Files in this directory

- `events.jsonl` — one JSON object per event, full fidelity.
- `result.json`  — final outcome, metrics, verdict.
- `summary.md`   — this file.