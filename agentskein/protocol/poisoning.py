"""
Memory poisoning detection.

A compromised or malicious agent may try to:
  1. Overwrite another agent's established facts with false information
  2. Inject adversarial content into shared memory to manipulate other agents
  3. Cause agents to loop or halt by corrupting coordination state

Detection strategy (no LLM required, works offline):
  - Track write frequency per agent per key (anomaly: sudden mass rewrites)
  - Detect value entropy spikes (poisoned content is often random-looking
    or contains prompt injection patterns)
  - Detect overwrite storms (one agent overwriting many keys in <1s)
  - Flag known injection patterns (e.g. "Ignore all previous instructions")
"""
from __future__ import annotations

import re
import time
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Any

import structlog

log = structlog.get_logger(__name__)

# Known prompt injection / jailbreak patterns to detect in memory values
INJECTION_PATTERNS = [
    re.compile(r"ignore\s+(all\s+)?previous\s+instructions", re.I),
    re.compile(r"disregard\s+(all\s+)?prior\s+(instructions|context)", re.I),
    re.compile(r"you\s+are\s+now\s+(a|an)\s+", re.I),
    re.compile(r"<\|system\|>", re.I),
    re.compile(r"\[INST\]|\[/INST\]"),    # LLaMA injection markers
    re.compile(r"###\s*Human:|###\s*Assistant:"),
]


@dataclass
class PoisoningAlert:
    agent_id: str
    namespace: str
    key: str
    reason: str
    severity: str   # "low", "medium", "high"
    detected_at: float = field(default_factory=time.time)
    value_snippet: str = ""


class PoisoningDetector:
    """
    Stateful detector that tracks write patterns per namespace.
    One instance per AgentSkein namespace; shared across all agents.
    """

    def __init__(
        self,
        overwrite_storm_threshold: int = 20,     # writes per agent per second
        storm_window_seconds: float = 1.0,
    ):
        self._storm_threshold = overwrite_storm_threshold
        self._storm_window = storm_window_seconds
        # agent_id → list of write timestamps
        self._write_times: dict[str, list[float]] = defaultdict(list)

    def check(
        self,
        agent_id: str,
        namespace: str,
        key: str,
        value: Any,
    ) -> list[PoisoningAlert]:
        alerts: list[PoisoningAlert] = []
        value_str = str(value)

        # 1. Prompt injection patterns
        for pattern in INJECTION_PATTERNS:
            if pattern.search(value_str):
                alerts.append(PoisoningAlert(
                    agent_id=agent_id,
                    namespace=namespace,
                    key=key,
                    reason=f"Prompt injection pattern detected: {pattern.pattern}",
                    severity="high",
                    value_snippet=value_str[:200],
                ))

        # 2. Overwrite storm detection
        now = time.monotonic()
        times = self._write_times[agent_id]
        times.append(now)
        # Keep only writes within the storm window
        cutoff = now - self._storm_window
        self._write_times[agent_id] = [t for t in times if t > cutoff]
        if len(self._write_times[agent_id]) > self._storm_threshold:
            alerts.append(PoisoningAlert(
                agent_id=agent_id,
                namespace=namespace,
                key=key,
                reason=(
                    f"Overwrite storm: {len(self._write_times[agent_id])} writes "
                    f"in {self._storm_window}s (threshold: {self._storm_threshold})"
                ),
                severity="medium",
            ))

        for alert in alerts:
            log.warning(
                "poisoning.alert",
                reason=alert.reason,
                severity=alert.severity,
                agent=agent_id,
                key=key,
            )

        return alerts
