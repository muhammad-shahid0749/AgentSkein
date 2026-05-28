"""
Shared result recorder for the real-world test scenarios.

Every scenario writes:
  * <results_dir>/<scenario>/events.jsonl   one JSON object per event
  * <results_dir>/<scenario>/result.json    the final aggregated outcome
  * <results_dir>/<scenario>/summary.md     a human/LLM readable run summary

The JSONL format is deliberately schema-light so an LLM can ingest it
without prior knowledge: every event is `{"ts": ..., "event": "...", ...}`
with whatever extra keys the scenario chose to log.
"""
from __future__ import annotations

import json
import os
import time
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Any


DEFAULT_RESULTS_DIR = os.getenv("AGENTSKEIN_RESULTS_DIR", "./test_results")


@dataclass
class ScenarioRecorder:
    """One recorder per scenario run. Use as a context manager.

    Example:
        async with ScenarioRecorder("multi_writer_race") as rec:
            rec.event("setup", agents=5)
            ...
            rec.set_outcome(passed=True, summary="...", metrics={...})
    """

    scenario: str
    results_dir: str = DEFAULT_RESULTS_DIR
    description: str = ""
    _start: float = field(default=0.0, init=False)
    _events: list[dict[str, Any]] = field(default_factory=list, init=False)
    _outcome: dict[str, Any] = field(default_factory=dict, init=False)
    _events_fh: Any = field(default=None, init=False)

    def __enter__(self) -> "ScenarioRecorder":
        self._start = time.time()
        out = Path(self.results_dir) / self.scenario
        out.mkdir(parents=True, exist_ok=True)
        self._events_fh = (out / "events.jsonl").open("w", encoding="utf-8")
        self.event(
            "scenario.start",
            scenario=self.scenario,
            description=self.description,
        )
        return self

    async def __aenter__(self) -> "ScenarioRecorder":
        return self.__enter__()

    def __exit__(self, exc_type, exc, tb) -> None:
        if exc is not None:
            self.event(
                "scenario.error",
                error_type=type(exc).__name__,
                error=str(exc),
            )
            self._outcome.setdefault("passed", False)
            self._outcome.setdefault("summary", f"unhandled {type(exc).__name__}: {exc}")
        self.event("scenario.end", duration_s=round(time.time() - self._start, 4))
        if self._events_fh:
            self._events_fh.close()
        self._write_result_json()
        self._write_summary_md()

    async def __aexit__(self, exc_type, exc, tb) -> None:
        return self.__exit__(exc_type, exc, tb)

    # ─── logging ──────────────────────────────────────────────────────────

    def event(self, event: str, **fields: Any) -> None:
        """Record one structured event. JSONL line, one per event."""
        rec = {
            "ts": round(time.time() - self._start, 4),
            "event": event,
            **fields,
        }
        self._events.append(rec)
        if self._events_fh:
            self._events_fh.write(json.dumps(rec, default=str) + "\n")
            self._events_fh.flush()

    def set_outcome(self, *, passed: bool, summary: str,
                    metrics: dict[str, Any] | None = None,
                    claim: str = "") -> None:
        self._outcome = {
            "passed": passed,
            "summary": summary,
            "claim": claim,
            "metrics": metrics or {},
        }
        self.event("scenario.outcome", **self._outcome)

    # ─── writers ──────────────────────────────────────────────────────────

    def _write_result_json(self) -> None:
        out = Path(self.results_dir) / self.scenario
        payload = {
            "scenario": self.scenario,
            "description": self.description,
            "duration_s": round(time.time() - self._start, 4),
            "event_count": len(self._events),
            **self._outcome,
        }
        (out / "result.json").write_text(
            json.dumps(payload, indent=2, default=str), encoding="utf-8"
        )

    def _write_summary_md(self) -> None:
        out = Path(self.results_dir) / self.scenario
        passed = self._outcome.get("passed")
        verdict = "PASS" if passed else ("FAIL" if passed is False else "INCOMPLETE")
        metrics = self._outcome.get("metrics") or {}

        lines: list[str] = []
        lines.append(f"# {self.scenario} — {verdict}")
        lines.append("")
        if self.description:
            lines.append(f"_{self.description}_")
            lines.append("")
        if self._outcome.get("claim"):
            lines.append(f"**Claim under test:** {self._outcome['claim']}")
            lines.append("")
        lines.append(f"**Verdict:** {verdict}")
        lines.append("")
        if self._outcome.get("summary"):
            lines.append("## Summary")
            lines.append("")
            lines.append(self._outcome["summary"])
            lines.append("")
        if metrics:
            lines.append("## Metrics")
            lines.append("")
            lines.append("| Metric | Value |")
            lines.append("|--------|-------|")
            for k, v in metrics.items():
                lines.append(f"| {k} | {v} |")
            lines.append("")
        lines.append("## Event timeline")
        lines.append("")
        lines.append("Each event is one line in `events.jsonl`. First 50 shown here:")
        lines.append("")
        lines.append("| t (s) | event | fields |")
        lines.append("|-------|-------|--------|")
        for ev in self._events[:50]:
            extras = {k: v for k, v in ev.items() if k not in ("ts", "event")}
            lines.append(
                f"| {ev['ts']:.3f} | `{ev['event']}` | "
                f"{json.dumps(extras, default=str)[:120]} |"
            )
        lines.append("")
        lines.append("## Files in this directory")
        lines.append("")
        lines.append("- `events.jsonl` — one JSON object per event, full fidelity.")
        lines.append("- `result.json`  — final outcome, metrics, verdict.")
        lines.append("- `summary.md`   — this file.")
        (out / "summary.md").write_text("\n".join(lines), encoding="utf-8")


def write_run_summary(results_dir: str, runs: list[dict[str, Any]]) -> None:
    """Write a top-level summary spanning every scenario in this run.

    `runs` is a list of {scenario, passed, summary, claim, duration_s, metrics}.
    Produces results_dir/run_summary.md and results_dir/run_summary.json.
    """
    out = Path(results_dir)
    out.mkdir(parents=True, exist_ok=True)
    (out / "run_summary.json").write_text(
        json.dumps({"runs": runs}, indent=2, default=str), encoding="utf-8"
    )

    total = len(runs)
    passed = sum(1 for r in runs if r.get("passed"))
    lines: list[str] = []
    lines.append("# AgentSkein — Real-World Test Run Summary")
    lines.append("")
    lines.append(f"**Scenarios:** {total}    **Passed:** {passed}    **Failed:** {total - passed}")
    lines.append("")
    lines.append("| Scenario | Verdict | Duration (s) | Headline |")
    lines.append("|----------|---------|--------------|----------|")
    for r in runs:
        verdict = "PASS" if r.get("passed") else "FAIL"
        head = (r.get("summary") or "").split("\n")[0][:120]
        lines.append(
            f"| `{r['scenario']}` | {verdict} | {r.get('duration_s', '?'):.2f} | {head} |"
        )
    lines.append("")
    lines.append("## What each scenario tests")
    lines.append("")
    for r in runs:
        lines.append(f"### `{r['scenario']}`")
        lines.append("")
        if r.get("claim"):
            lines.append(f"**Claim:** {r['claim']}")
            lines.append("")
        if r.get("metrics"):
            lines.append("| Metric | Value |")
            lines.append("|--------|-------|")
            for k, v in r["metrics"].items():
                lines.append(f"| {k} | {v} |")
            lines.append("")
        if r.get("summary"):
            lines.append(r["summary"])
            lines.append("")
    (out / "run_summary.md").write_text("\n".join(lines), encoding="utf-8")
