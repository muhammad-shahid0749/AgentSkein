"""OrchestratorAgent — runs the full pipeline."""
import sys, os
_project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _project_root not in sys.path:
    sys.path.insert(0, _project_root)

import asyncio, time, httpx
from agents.base_agent       import BaseAgent
from agents.researcher_agent import ResearcherAgent
from agents.analyst_agent    import AnalystAgent
from agents.writer_agent     import WriterAgent
from agents.safety_agent     import SafetyAgent
from rich.console import Console
from rich.table   import Table
from rich.rule    import Rule
from rich         import box

console = Console()


class OrchestratorAgent(BaseAgent):

    async def run(self) -> dict:
        t0 = time.perf_counter()
        self._log("pipeline.start", base_url=self.base_url)
        console.print()
        console.print(Rule("[bold white]AgentSkein — GitHub AI Ecosystem Intelligence Pipeline[/bold white]"))
        console.print()

        try:
            async with httpx.AsyncClient(timeout=5.0) as client:
                resp = await client.get(f"{self.base_url}/health")
                health = resp.json()
            self._log("api.health.ok", backend=health.get('backend'))
            console.print(f"[green]  v AgentSkein API[/green] - backend: [cyan]{health.get('backend')}[/cyan]")
        except Exception as e:
            self._log("api.health.failed", error=str(e))
            console.print(f"[bold red]  x Cannot reach API at {self.base_url}[/bold red]")
            console.print("  Start first:  python examples\\n8n_api_server\\server.py")
            return {"success": False, "error": str(e)}

        await self.init_namespace("GitHub AI Ecosystem Intelligence")
        self._log("namespace.init", namespace=self.namespace)
        console.print(f"[green]  v Namespace ready[/green]")
        console.print()

        console.print(Rule("[cyan]Phase 1 - Parallel: 3 Researchers (same query, different metrics)[/cyan]"))
        console.print()
        console.print("  All 3 agents search: [bold]\"ai agents python\"[/bold] - the SAME query")
        console.print()
        console.print("  Researcher-1  metric: POPULARITY   ranks by star count")
        console.print("  Researcher-2  metric: ACTIVITY     ranks by most recently updated")
        console.print("  Researcher-3  metric: ADOPTION     ranks by fork count")
        console.print()
        console.print("  Each writes to disjoint top-level keys (analysis-by-*) + one shared verdict key.")
        console.print()

        r1 = ResearcherAgent("Researcher-1", self.namespace, self.base_url, metric="POPULARITY")
        r2 = ResearcherAgent("Researcher-2", self.namespace, self.base_url, metric="ACTIVITY")
        r3 = ResearcherAgent("Researcher-3", self.namespace, self.base_url, metric="ADOPTION")
        sa = SafetyAgent("Safety-Monitor", self.namespace, self.base_url)

        self._log("phase1.start",
                  agents=["Researcher-1","Researcher-2","Researcher-3","Safety-Monitor"])
        res_r1, res_r2, res_r3, res_sa = await asyncio.gather(
            r1.run(), r2.run(), r3.run(), sa.run(), return_exceptions=True
        )
        self._log("phase1.complete")
        console.print()

        console.print(Rule("[magenta]Phase 2 - Analyst[/magenta]"))
        self._log("phase2.start", agent="Analyst")
        res_an = await AnalystAgent("Analyst", self.namespace, self.base_url).run()
        self._log("phase2.complete")
        console.print()

        console.print(Rule("[green]Phase 3 - Writer[/green]"))
        self._log("phase3.start", agent="Writer")
        # Flush orchestrator log BEFORE writer runs so writer can read it.
        await self.flush_activity_log(branch="main")
        res_wr = await WriterAgent("Writer", self.namespace, self.base_url).run()
        self._log("phase3.complete")
        # Final flush so the completed log is on main for any post-mortem read.
        await self.flush_activity_log(branch="main")

        elapsed = time.perf_counter() - t0
        snap    = await self.snapshot(branch="main")
        data    = snap.get("data", {}) or {}
        repos   = sum(1 for k in data if k.startswith("repo-"))

        def sg(r, k, d="?"):
            return r.get(k, d) if isinstance(r, dict) else d

        console.print()
        console.print(Rule("[bold white]Done[/bold white]"))
        console.print()

        tbl = Table(box=box.ROUNDED, header_style="bold cyan")
        tbl.add_column("Agent",  width=18)
        tbl.add_column("Task",   width=42)
        tbl.add_column("Status", justify="center", width=8)
        tbl.add_column("Result", justify="right",  width=14)
        tbl.add_row("Researcher-1","Searched by POPULARITY (stars)",     "[green]v[/green]",f"{sg(res_r1,'keys_written')} repos")
        tbl.add_row("Researcher-2","Searched by ACTIVITY (last commit)", "[green]v[/green]",f"{sg(res_r2,'keys_written')} repos")
        tbl.add_row("Researcher-3","Searched by ADOPTION (forks)",       "[green]v[/green]",f"{sg(res_r3,'keys_written')} repos")
        tbl.add_row("Safety-Monitor","Injection + storm tests",          "[green]v[/green]",f"{sg(res_sa,'passed_tests')}/{sg(res_sa,'total_tests')}")
        tbl.add_row("Analyst","Statistics + conflict story",             "[green]v[/green]",f"{sg(res_an,'repos_analysed')} repos")
        tbl.add_row("Writer","AI Ecosystem Report",                      "[green]v[/green]","saved")
        console.print(tbl)
        console.print()

        info = Table(box=box.SIMPLE, show_header=False)
        info.add_column(style="dim",   width=30)
        info.add_column(style="white", width=35)
        info.add_row("Total repos on main",    str(repos))
        info.add_row("Total AgentSkein keys",  str(snap.get("count", len(data))))
        info.add_row("Disjoint analysis keys", "3 (analysis-by-popularity/activity/adoption)")
        info.add_row("Shared verdict survivor", str((data.get("verdict") or {}).get("chosen_by","?")))
        info.add_row("Safety score",            f"{sg(res_sa,'passed_tests')}/{sg(res_sa,'total_tests')}")
        info.add_row("Total time",              f"{elapsed:.1f}s")
        console.print(info)
        console.print()
        console.print("[bold green]  Open  agents/ai_ecosystem_report.txt[/bold green]")
        console.print()
        return {
            "success": True,
            "repos":   repos,
            "elapsed": elapsed,
            "perspectives_preserved": sg(res_an, "perspectives_preserved", 0),
            "perspectives_expected":  sg(res_an, "perspectives_expected", 3),
        }
