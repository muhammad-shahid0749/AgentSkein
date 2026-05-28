"""
Experiment harness for the README / AGENTS_INTEGRATION_GUIDE walkthrough.

Every experiment captures:
    name            short slug
    source_doc      "README.md" / "AGENTS_INTEGRATION_GUIDE.md" / "docs/README.md"
    source_lines    e.g. "L122-L147"
    claim           one-line description of what the experiment proves
    command         the shell-equivalent the docs tell the user to run
    status          "pass" | "fail" | "skipped"
    skip_reason     populated when status="skipped"
    duration_s      wall-clock time
    exit_code       int for subprocess experiments
    stdout / stderr captured output (truncated)
    error           Python exception name + message (in-process failures)

Two run styles:
  * Experiment.subprocess(...)        run an external command, capture pipe
  * Experiment.callable(...)          run an async/sync python callable inline

Results land in:
    <results_dir>/<experiment_name>/result.json
    <results_dir>/<experiment_name>/stdout.txt
    <results_dir>/<experiment_name>/stderr.txt
    <results_dir>/run_summary.{md,json}      written at end by write_run_summary()
"""
from __future__ import annotations

import asyncio
import importlib
import io
import json
import os
import shutil
import subprocess
import sys
import time
import traceback
from contextlib import redirect_stderr, redirect_stdout
from dataclasses import dataclass, asdict, field
from pathlib import Path
from typing import Any, Awaitable, Callable

DEFAULT_RESULTS_DIR = os.getenv(
    "AGENTSKEIN_EXPERIMENT_RESULTS_DIR",
    str(Path(__file__).resolve().parents[2] / "experiment_results"),
)

_TRUNCATE = 8000  # max bytes per captured stream


def _truncate(s: str, n: int = _TRUNCATE) -> str:
    if s is None:
        return ""
    if len(s) <= n:
        return s
    return s[:n] + f"\n... [truncated, total {len(s)} chars]"


@dataclass
class ExperimentResult:
    name: str
    source_doc: str
    source_lines: str
    claim: str
    command: str
    status: str = "pending"           # pass / fail / skipped
    skip_reason: str = ""
    duration_s: float = 0.0
    exit_code: int | None = None
    stdout: str = ""
    stderr: str = ""
    error: str = ""
    extra: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["stdout"] = _truncate(self.stdout)
        d["stderr"] = _truncate(self.stderr)
        return d


class Experiment:
    """Builder for one experiment. Use `with` to ensure results are flushed."""

    def __init__(
        self,
        name: str,
        *,
        source_doc: str,
        source_lines: str,
        claim: str,
        command: str = "",
        results_dir: str = DEFAULT_RESULTS_DIR,
    ):
        self.result = ExperimentResult(
            name=name,
            source_doc=source_doc,
            source_lines=source_lines,
            claim=claim,
            command=command,
        )
        self._results_dir = Path(results_dir)
        self._out_dir = self._results_dir / name
        self._out_dir.mkdir(parents=True, exist_ok=True)
        self._start: float = 0.0

    # ─── public helpers ───────────────────────────────────────────────────

    def skip(self, reason: str) -> None:
        self.result.status = "skipped"
        self.result.skip_reason = reason

    def fail(self, error: str) -> None:
        self.result.status = "fail"
        self.result.error = error

    def passed(self) -> None:
        self.result.status = "pass"

    # ─── runners ──────────────────────────────────────────────────────────

    def run_subprocess(
        self,
        argv: list[str],
        *,
        cwd: str | None = None,
        env_extra: dict[str, str] | None = None,
        timeout_s: float = 120.0,
        accept_codes: tuple[int, ...] = (0,),
    ) -> None:
        """Run an external command, capture pipes and exit-code.

        accept_codes determines which exit-codes mean "pass".
        """
        env = os.environ.copy()
        if env_extra:
            env.update(env_extra)

        # First check executable exists if argv[0] looks like a path or name
        if argv and not argv[0].startswith("python") and not Path(argv[0]).is_absolute():
            if shutil.which(argv[0]) is None and argv[0] not in ("pytest", "cargo"):
                # Allow these names to resolve via shutil.which during run
                pass

        self._start = time.time()
        try:
            proc = subprocess.run(
                argv,
                capture_output=True,
                text=True,
                cwd=cwd,
                env=env,
                timeout=timeout_s,
                check=False,
            )
        except FileNotFoundError as e:
            self._record_skip_or_fail(
                skip=True,
                reason=f"command not found: {argv[0]!r} ({e})",
            )
            return
        except subprocess.TimeoutExpired as e:
            self.result.duration_s = round(time.time() - self._start, 4)
            self.result.stdout = (e.stdout or "")
            self.result.stderr = (e.stderr or "") + f"\n[TIMEOUT after {timeout_s}s]"
            self.fail(f"timeout after {timeout_s}s")
            return

        self.result.duration_s = round(time.time() - self._start, 4)
        self.result.stdout = proc.stdout or ""
        self.result.stderr = proc.stderr or ""
        self.result.exit_code = proc.returncode
        if proc.returncode in accept_codes:
            self.passed()
        else:
            self.fail(f"exit code {proc.returncode} not in {accept_codes}")

    def run_callable(
        self,
        func: Callable[[], Any] | Callable[[], Awaitable[Any]],
        *,
        require_modules: tuple[str, ...] = (),
    ) -> Any:
        """Run a python callable inline, capturing stdout/stderr.

        If any module in require_modules cannot be imported, the experiment
        is skipped (this is how we handle optional integrations).
        """
        for mod in require_modules:
            try:
                importlib.import_module(mod)
            except ImportError as e:
                self._record_skip_or_fail(
                    skip=True,
                    reason=f"module {mod!r} not installed: {e}",
                )
                return None

        stdout_buf = io.StringIO()
        stderr_buf = io.StringIO()
        self._start = time.time()
        ret: Any = None
        try:
            with redirect_stdout(stdout_buf), redirect_stderr(stderr_buf):
                if asyncio.iscoroutinefunction(func):
                    ret = asyncio.run(func())
                else:
                    ret = func()
                    if asyncio.iscoroutine(ret):
                        ret = asyncio.get_event_loop().run_until_complete(ret)
            self.passed()
        except AssertionError as e:
            self.fail(f"AssertionError: {e}")
            stderr_buf.write("\n" + traceback.format_exc())
        except Exception as e:
            self.fail(f"{type(e).__name__}: {e}")
            stderr_buf.write("\n" + traceback.format_exc())
        finally:
            self.result.duration_s = round(time.time() - self._start, 4)
            self.result.stdout = stdout_buf.getvalue()
            self.result.stderr = stderr_buf.getvalue()
        return ret

    def attach(self, **kwargs: Any) -> None:
        """Attach arbitrary scenario-specific facts to the result."""
        self.result.extra.update(kwargs)

    # ─── persistence ──────────────────────────────────────────────────────

    def write(self) -> None:
        (self._out_dir / "result.json").write_text(
            json.dumps(self.result.to_dict(), indent=2, default=str), encoding="utf-8"
        )
        (self._out_dir / "stdout.txt").write_text(self.result.stdout, encoding="utf-8")
        (self._out_dir / "stderr.txt").write_text(self.result.stderr, encoding="utf-8")

    # ─── context manager ──────────────────────────────────────────────────

    def __enter__(self) -> "Experiment":
        return self

    def __exit__(self, exc_type, exc, tb) -> bool:
        if exc is not None and self.result.status == "pending":
            self.fail(f"{exc_type.__name__}: {exc}")
            self.result.stderr += "\n" + traceback.format_exc()
        if self.result.status == "pending":
            # Caller forgot to mark; default to pass if nothing went wrong.
            self.passed()
        self.write()
        # Don't swallow real exceptions outside the harness
        return True

    # ─── internals ────────────────────────────────────────────────────────

    def _record_skip_or_fail(self, *, skip: bool, reason: str) -> None:
        self.result.duration_s = round(time.time() - self._start, 4) if self._start else 0.0
        if skip:
            self.skip(reason)
        else:
            self.fail(reason)


# ───────────────────────── run-level summary ─────────────────────────────


def write_run_summary(results_dir: str, results: list[ExperimentResult]) -> None:
    out = Path(results_dir)
    out.mkdir(parents=True, exist_ok=True)
    (out / "run_summary.json").write_text(
        json.dumps([r.to_dict() for r in results], indent=2, default=str),
        encoding="utf-8",
    )

    total = len(results)
    passed = sum(1 for r in results if r.status == "pass")
    failed = sum(1 for r in results if r.status == "fail")
    skipped = sum(1 for r in results if r.status == "skipped")

    lines: list[str] = []
    lines.append("# AgentSkein — Documentation Experiments Run Summary")
    lines.append("")
    lines.append(
        f"**Total:** {total}    **Pass:** {passed}    "
        f"**Fail:** {failed}    **Skipped:** {skipped}"
    )
    lines.append("")
    lines.append(
        "Every row below is a literal claim made in `README.md` or "
        "`AGENTS_INTEGRATION_GUIDE.md`. If a row is FAIL, the documentation "
        "is broken; if it is SKIPPED, the row tells you what dependency is missing."
    )
    lines.append("")

    # Headline table
    lines.append("| # | Experiment | Source | Status | Duration | Notes |")
    lines.append("|---|-----------|--------|--------|----------|-------|")
    for i, r in enumerate(results, start=1):
        verdict = {"pass": "PASS", "fail": "FAIL", "skipped": "SKIP"}.get(r.status, r.status.upper())
        note = (
            r.skip_reason if r.status == "skipped"
            else (r.error or "")
            if r.status == "fail" else ""
        )
        lines.append(
            f"| {i} | `{r.name}` | {r.source_doc} {r.source_lines} | {verdict} | "
            f"{r.duration_s:.2f}s | {note[:80]} |"
        )
    lines.append("")

    # Per-experiment detail
    for r in results:
        verdict = {"pass": "PASS", "fail": "FAIL", "skipped": "SKIP"}.get(r.status, r.status.upper())
        lines.append(f"## `{r.name}` — {verdict}")
        lines.append("")
        lines.append(f"- **Source:** {r.source_doc} {r.source_lines}")
        lines.append(f"- **Claim:** {r.claim}")
        if r.command:
            lines.append("- **Command:**")
            lines.append("")
            lines.append("    ```")
            lines.append(f"    {r.command}")
            lines.append("    ```")
        lines.append(f"- **Duration:** {r.duration_s:.2f}s")
        if r.exit_code is not None:
            lines.append(f"- **Exit code:** {r.exit_code}")
        if r.status == "skipped":
            lines.append(f"- **Skip reason:** {r.skip_reason}")
        if r.status == "fail":
            lines.append(f"- **Failure:** {r.error}")
        if r.extra:
            lines.append("- **Extra:**")
            for k, v in r.extra.items():
                lines.append(f"    - `{k}`: {v}")
        # Last few lines of output for at-a-glance
        if r.stdout:
            tail = "\n".join(r.stdout.splitlines()[-15:])
            lines.append("")
            lines.append("<details><summary>stdout (tail)</summary>")
            lines.append("")
            lines.append("```")
            lines.append(tail)
            lines.append("```")
            lines.append("</details>")
        if r.stderr:
            tail = "\n".join(r.stderr.splitlines()[-15:])
            lines.append("")
            lines.append("<details><summary>stderr (tail)</summary>")
            lines.append("")
            lines.append("```")
            lines.append(tail)
            lines.append("```")
            lines.append("</details>")
        lines.append("")

    (out / "run_summary.md").write_text("\n".join(lines), encoding="utf-8")
