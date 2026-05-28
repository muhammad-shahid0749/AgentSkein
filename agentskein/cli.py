"""
AgentSkein CLI — real-time dashboard for monitoring shared memory.

Usage:
    agentskein watch --namespace task-42 --redis redis://localhost:6379
    agentskein snapshot --namespace task-42
    agentskein branches --namespace task-42
    agentskein write --namespace task-42 --key mykey --value '{"x":1}'
"""
import asyncio
import json

import click
from rich import box
from rich.columns import Columns
from rich.console import Console
from rich.live import Live
from rich.panel import Panel
from rich.table import Table

from .client import AgentSkein
from .storage.redis_backend import RedisBackend

console = Console()


@click.group()
def main() -> None:
    """AgentSkein — cross-agent shared memory with conflict resolution."""
    pass


@main.command()
@click.option("--namespace", "-n", required=True)
@click.option("--redis", "-r", default="redis://localhost:6379/0")
@click.option("--branch", "-b", default="main")
def snapshot(namespace: str, redis: str, branch: str) -> None:
    """Print all key-value pairs in a namespace branch."""
    async def _run() -> None:
        mesh = AgentSkein("cli", namespace, branch, RedisBackend(redis))
        await mesh.init()
        data = await mesh.snapshot()
        if not data:
            console.print(f"[dim]No entries in {namespace}/{branch}[/dim]")
            await mesh.close()
            return
        table = Table(title=f"Snapshot: {namespace}/{branch}", box=box.ROUNDED)
        table.add_column("Key", style="cyan")
        table.add_column("Value", style="white")
        table.add_column("Type", style="dim")
        for k, v in data.items():
            table.add_row(k, str(v)[:80], type(v).__name__)
        console.print(table)
        await mesh.close()
    asyncio.run(_run())


@main.command()
@click.option("--namespace", "-n", required=True)
@click.option("--redis", "-r", default="redis://localhost:6379/0")
@click.option("--interval", "-i", default=2.0, help="Refresh interval in seconds")
def watch(namespace: str, redis: str, interval: float) -> None:
    """Live-updating dashboard for a namespace."""
    async def _run() -> None:
        # [B6] Create backend and mesh ONCE outside the loop.
        # Original code leaked a new Redis connection on every tick.
        backend = RedisBackend(redis)
        mesh = AgentSkein("cli-watcher", namespace, branch="main", backend=backend)
        await mesh.init()
        with Live(console=console, refresh_per_second=2) as live:
            while True:
                state = await backend.get_namespace(namespace)
                entries = await backend.get_branch_entries(namespace, "main")

                header = Panel(
                    f"[bold cyan]AgentSkein[/bold cyan]  "
                    f"namespace=[green]{namespace}[/green]  "
                    f"entries=[yellow]{len(entries)}[/yellow]  "
                    f"conflicts resolved=[red]"
                    f"{state.total_conflicts_resolved if state else 0}[/red]",
                    box=box.ROUNDED,
                )
                table = Table(box=box.SIMPLE)
                table.add_column("Key", style="cyan", width=24)
                table.add_column("Value", width=40)
                table.add_column("Written by", style="dim", width=16)
                table.add_column("Branch", style="dim", width=10)
                for e in sorted(entries, key=lambda x: x.updated_at, reverse=True)[:20]:
                    table.add_row(
                        e.key, str(e.value)[:40], e.agent_id, e.branch
                    )
                live.update(Columns([header, table]))
                await asyncio.sleep(interval)
        await backend.close()
    asyncio.run(_run())


@main.command()
@click.option("--namespace", "-n", required=True)
@click.option("--redis", "-r", default="redis://localhost:6379/0")
def branches(namespace: str, redis: str) -> None:
    """List all branches in a namespace."""
    async def _run() -> None:
        backend = RedisBackend(redis)
        state = await backend.get_namespace(namespace)
        if state is None:
            console.print(f"[red]Namespace '{namespace}' not found.[/red]")
            await backend.close()
            return
        table = Table(title=f"Branches: {namespace}", box=box.ROUNDED)
        table.add_column("Branch", style="cyan")
        table.add_column("Parent", style="dim")
        table.add_column("Created by", style="dim")
        table.add_column("Merged", style="dim")
        for name, branch in state.branches.items():
            table.add_row(
                name,
                branch.parent_branch,
                branch.created_by,
                "✓" if branch.is_merged else "",
            )
        console.print(table)
        await backend.close()
    asyncio.run(_run())


@main.command()
@click.option("--namespace", "-n", required=True)
@click.option("--key", "-k", required=True)
@click.option("--value", "-v", required=True, help="JSON value")
@click.option("--agent", "-a", default="cli-agent")
@click.option("--redis", "-r", default="redis://localhost:6379/0")
def write(namespace: str, key: str, value: str, agent: str, redis: str) -> None:
    """Write a value to a namespace key."""
    async def _run() -> None:
        try:
            parsed_value = json.loads(value)
        except json.JSONDecodeError:
            parsed_value = value  # treat as plain string
        mesh = AgentSkein(agent, namespace, backend=RedisBackend(redis))
        await mesh.init()
        entry = await mesh.write(key, parsed_value)
        console.print(
            f"[green]✓[/green] Wrote key=[cyan]{key}[/cyan] "
            f"id=[dim]{entry.id}[/dim]"
        )
        await mesh.close()
    asyncio.run(_run())
