"""
ResearcherAgent — searches GitHub for "ai agents python" using a specific
evaluation metric. All three researchers answer the SAME question but use
DIFFERENT criteria.

  Researcher-1  metric: POPULARITY   -> ranks by stargazers_count
  Researcher-2  metric: ACTIVITY     -> ranks by pushed_at
  Researcher-3  metric: ADOPTION     -> ranks by forks_count

DEMO DESIGN - TWO DISTINCT CONFLICT PATTERNS
─────────────────────────────────────────────
Pattern A - disjoint top-level keys (PROVES PRESERVATION)
    R1 writes  -> "analysis-by-popularity"     (only R1 writes this key)
    R2 writes  -> "analysis-by-activity"       (only R2 writes this key)
    R3 writes  -> "analysis-by-adoption"       (only R3 writes this key)

    Because the three top-level keys are disjoint, the 3-way merge engine
    has nothing to conflict on at the namespace level - every merge_to(main)
    is a clean addition. After all three researchers merge, main contains
    ALL THREE keys with ALL THREE researchers' full analyses preserved.

    NOTE: We deliberately do NOT use a single shared key like
    `best-library = {popularity:{...}, activity:{...}, adoption:{...}}`
    with nested sub-keys per researcher. Trace through 3-way merge for
    three sequential merges: by the third merger the base_value carries
    the prior sub-keys and the engine treats "absent from ours" as
    "deleted by ours" (correct Git semantics), so the first researcher's
    sub-key gets dropped. Disjoint TOP-LEVEL keys avoid this entirely.

Pattern B - same-key concurrent writes  (HONESTLY DEMONSTRATES DETECTION)
    All three write to "verdict" with a flat schema:
        {winner_repo, winner_stars, winner_forks, winner_metric,
         chosen_by, confidence}
    Every scalar field differs across researchers. The 3-way merge
    engine DETECTS the conflict via vector clocks but cannot produce a
    union on conflicting scalars - the last writer's values survive on
    the conflicting fields. The Writer report explains this honestly:
        * conflict WAS detected (audit trail recorded)
        * for genuine union-preservation, use Pattern A (disjoint keys)
        * for textual union, use MERGE_SEMANTIC with an LLM callable

Pattern C - overlapping repo keys  (REPO-LEVEL CONFLICTS)
    Individual "repo-{name}" keys are written by whichever researcher
    finds that repo. Multiple researchers may find the same repo (e.g.
    AutoGPT is highly starred AND highly forked AND recently updated).
    When that happens, structural merge unions non-overlapping fields
    in the repo dict and falls back to LWW on overlapping fields.
"""
import sys, os
_project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _project_root not in sys.path:
    sys.path.insert(0, _project_root)

import asyncio
from collections import Counter
from agents.base_agent import BaseAgent
from rich.console import Console

console = Console()
GITHUB_API = "https://api.github.com"

SHARED_QUERY = "ai agents python"

SORT_OPTIONS = {
    "POPULARITY": {"sort": "stars",    "label": "most starred",          "field": "stargazers_count"},
    "ACTIVITY":   {"sort": "updated",  "label": "most recently updated", "field": "pushed_at"},
    "ADOPTION":   {"sort": "forks",    "label": "most forked",           "field": "forks_count"},
}


def health_score(repos, metric):
    """Compute a 0-10 ecosystem health score based on this researcher's metric."""
    if not repos:
        return 0.0
    if metric == "POPULARITY":
        avg = sum(r.get("stargazers_count", 0) for r in repos) / len(repos)
        return round(min(avg / 1000, 10.0), 2)
    elif metric == "ACTIVITY":
        from datetime import datetime, timezone
        now = datetime.now(timezone.utc)
        ages = []
        for r in repos:
            try:
                pushed = datetime.fromisoformat(r.get("pushed_at","").replace("Z","+00:00"))
                days_ago = (now - pushed).days
                ages.append(days_ago)
            except Exception:
                pass
        if not ages:
            return 0.0
        avg_age = sum(ages) / len(ages)
        return round(max(0, 10 - avg_age / 30), 2)
    elif metric == "ADOPTION":
        avg = sum(r.get("forks_count", 0) for r in repos) / len(repos)
        return round(min(avg / 100, 10.0), 2)
    return 0.0


class ResearcherAgent(BaseAgent):
    """metric: one of "POPULARITY", "ACTIVITY", "ADOPTION" """

    def __init__(self, agent_id, namespace,
                 base_url="http://localhost:8765", metric="POPULARITY"):
        super().__init__(agent_id, namespace, base_url)
        self.metric = metric
        self.sort_config = SORT_OPTIONS[metric]

    async def _github_get(self, url):
        import httpx
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                r = await client.get(url, headers={
                    "User-Agent": "AgentSkein-Agent/1.0",
                    "Accept":     "application/vnd.github+json",
                })
                if r.status_code == 403:
                    console.print(f"[yellow]  [{self.agent_id}] Rate limit - waiting 15s ...[/yellow]")
                    await asyncio.sleep(15)
                    r = await client.get(url, headers={
                        "User-Agent": "AgentSkein-Agent/1.0",
                        "Accept":     "application/vnd.github+json",
                    })
                r.raise_for_status()
                return r.json()
        except Exception as e:
            self.errors.append(f"GitHub fetch failed: {e}")
            return None

    async def run(self) -> dict:
        sort_label = self.sort_config["label"]
        console.print(
            f"\n[bold blue][{self.agent_id}][/bold blue] "
            f"Searching GitHub: \"{SHARED_QUERY}\" sorted by {self.metric} ({sort_label}) ..."
        )

        self._log("run.start",
                  metric=self.metric, query=SHARED_QUERY, sort_label=sort_label)

        await self.init_namespace("GitHub AI Ecosystem Intelligence")
        self._log("namespace.init", namespace=self.namespace)

        branch = f"branch/{self.agent_id}"
        await self.fork(branch)
        self._log("branch.fork", branch=branch, parent="main")

        # ── Real GitHub API call (same query, different sort) ──────────────────
        url = (
            f"{GITHUB_API}/search/repositories"
            f"?q={SHARED_QUERY.replace(' ', '+')}"
            f"&sort={self.sort_config['sort']}"
            f"&order=desc&per_page=10"
        )
        self._log("github.fetch.start", url=url, sort=self.sort_config['sort'])
        data = await self._github_get(url)

        if not data or "items" not in data:
            console.print(f"[red]  [{self.agent_id}] GitHub API returned no results[/red]")
            self._log("github.fetch.failed", error="no data returned")
            await self.flush_activity_log(branch=branch)
            return {"success": False, "keys_written": 0, "errors": self.errors}

        items       = data["items"]
        total_found = data.get("total_count", 0)
        self._log("github.fetch.success",
                  total_count=total_found, fetched=len(items))

        console.print(
            f"[dim]  [{self.agent_id}] GitHub: {total_found:,} total results for "
            f"\"{SHARED_QUERY}\" - analysing top {len(items)} by {self.metric}[/dim]"
        )

        # ── Write each repo to AgentSkein ─────────────────────────────────────
        keys_written = 0
        raw_items    = []

        for repo in items:
            name    = repo.get("full_name", "")
            desc    = repo.get("description", "") or ""
            stars   = repo.get("stargazers_count", 0)
            forks   = repo.get("forks_count", 0)
            lang    = repo.get("language") or "Unknown"
            topics  = repo.get("topics", [])
            updated = repo.get("pushed_at", "")[:10]
            license_name = (repo.get("license") or {}).get("name", "No license")
            owner   = repo.get("owner", {}).get("login", "")

            repo_key = f"repo-{name.replace('/','--')}"
            check = await self.check_poison(repo_key, desc)
            if not check.get("safe", True):
                self._log("poison.blocked", key=repo_key,
                          alerts=check.get("alerts", []))
                continue

            entry = {
                "name": name, "description": desc[:200],
                "stars": stars, "forks": forks, "language": lang,
                "topics": topics[:5], "last_commit": updated,
                "license": license_name, "owner": owner,
                "ranked_by": self.metric,
                "found_by":  self.agent_id,
            }
            result = await self.write(
                repo_key, entry,
                branch=branch, strategy="merge_structural"
            )
            if result.get("success"):
                keys_written += 1
                raw_items.append(repo)
                self._log("write.repo", key=repo_key, stars=stars,
                          forks=forks, language=lang)
                console.print(
                    f"[dim]  [{self.agent_id}] "
                    f"{stars:>7,} stars  {forks:>6,} forks  "
                    f"{name:<38}  [{lang}][/dim]"
                )

        if not raw_items:
            await self.flush_activity_log(branch=branch)
            return {"success": False, "keys_written": 0, "errors": self.errors}

        # ── Determine this researcher's #1 pick ───────────────────────────────
        sort_field = self.sort_config["field"]
        if sort_field == "pushed_at":
            best = max(raw_items, key=lambda r: r.get("pushed_at", ""))
        else:
            best = max(raw_items, key=lambda r: r.get(sort_field, 0))

        best_name    = best.get("full_name", "")
        best_stars   = best.get("stargazers_count", 0)
        best_forks   = best.get("forks_count", 0)
        best_updated = best.get("pushed_at", "")[:10]
        best_lang    = best.get("language") or "Unknown"
        best_desc    = (best.get("description") or "")[:120]

        lang_counts  = Counter(r.get("language") or "Unknown" for r in raw_items)
        top_lang     = lang_counts.most_common(1)[0][0]
        h_score      = health_score(raw_items, self.metric)
        avg_stars    = round(sum(r.get("stargazers_count",0) for r in raw_items) / len(raw_items))
        avg_forks    = round(sum(r.get("forks_count",0) for r in raw_items) / len(raw_items))

        console.print(
            f"[bold blue]  [{self.agent_id}][/bold blue] "
            f"Best by {self.metric}: [yellow]{best_name}[/yellow] | "
            f"{best_stars:,} stars  {best_forks:,} forks  "
            f"health_score={h_score}"
        )

        # ══════════════════════════════════════════════════════════════════════
        # PATTERN A - DISJOINT TOP-LEVEL KEY  (one per researcher)
        # ══════════════════════════════════════════════════════════════════════
        analysis_key = f"analysis-by-{self.metric.lower()}"
        analysis_payload = {
            "by_agent":       self.agent_id,
            "metric":         self.metric,
            "metric_label":   sort_label,
            "best_repo": {
                "name":        best_name,
                "stars":       best_stars,
                "forks":       best_forks,
                "language":    best_lang,
                "last_commit": best_updated,
                "description": best_desc,
            },
            "rationale": (
                f"Ranked top-10 results by {self.metric.lower()} ({sort_label}). "
                f"#1 = {best_name} with {best_stars:,} stars, {best_forks:,} forks, "
                f"last commit {best_updated}."
            ),
            "ecosystem_health_score": h_score,
            "ecosystem_health_methodology": (
                f"0-10 score computed from {self.metric.lower()} of top-10 results"
            ),
            "top_language":   top_lang,
            "avg_stars":      avg_stars,
            "avg_forks":      avg_forks,
            "repos_examined": len(raw_items),
            "recommendation": (
                f"Based on {self.metric.lower()}, the standout library is "
                f"{best_name} ({best_stars:,} stars, {best_forks:,} forks, "
                f"last commit {best_updated}). Dominant language: {top_lang}."
            ),
        }
        await self.write(
            analysis_key, analysis_payload,
            branch=branch, strategy="merge_structural"
        )
        self._log("write.disjoint_analysis",
                  key=analysis_key, metric=self.metric,
                  best_repo=best_name, score=h_score)

        # ══════════════════════════════════════════════════════════════════════
        # PATTERN B - SHARED SAME-KEY WRITE  ("verdict")
        # ══════════════════════════════════════════════════════════════════════
        verdict_payload = {
            "winner_repo":    best_name,
            "winner_stars":   best_stars,
            "winner_forks":   best_forks,
            "winner_metric":  self.metric,
            "chosen_by":      self.agent_id,
            "confidence":     h_score,
        }
        await self.write(
            "verdict", verdict_payload,
            branch=branch, strategy="merge_structural"
        )
        self._log("write.shared_verdict",
                  key="verdict", winner_repo=best_name, metric=self.metric)

        # ── Flush activity log + merge to main ────────────────────────────────
        self._log("merge.start", from_branch=branch, to_branch="main")
        await self.flush_activity_log(branch=branch)

        merge = await self.merge(
            from_branch=branch, to_branch="main", strategy="merge_structural"
        )
        self._log("merge.complete",
                  merged_count=merge.get('merged_count', 0),
                  conflict_count=merge.get('conflict_count', 0))
        await self.flush_activity_log(branch=branch)
        await self.flush_activity_log(branch="main")

        console.print(
            f"[bold blue]  [{self.agent_id}][/bold blue] "
            f"Merged {merge.get('merged_count',0)} keys | "
            f"{merge.get('conflict_count',0)} auto-resolved"
        )

        return {
            "success": True, "keys_written": keys_written,
            "best_repo": best_name, "best_stars": best_stars,
            "metric": self.metric, "health_score": h_score,
            "analysis_key": analysis_key,
            "errors": self.errors,
        }
