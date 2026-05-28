import sys
import os
import time
import httpx
import asyncio
from typing import Any, Optional, Dict, List

# Add the project root to sys.path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

class BaseAgent:
    def __init__(self, agent_id: str, namespace: str, base_url: str = "http://localhost:8765"):
        self.agent_id = agent_id
        self.namespace = namespace
        self.base_url = base_url
        self.errors = []
        # ─── Activity log infrastructure ─────────────────────────────────────
        # Every agent action gets recorded here with a monotonic step counter
        # and a wall-clock timestamp. The WriterAgent flushes these logs into
        # the final report so a reviewer can see exactly what every agent did.
        self.activity: List[Dict[str, Any]] = []
        self._step_counter = 0
        self._t_start = time.time()

    # ── Activity logging ──────────────────────────────────────────────────────

    def _log(self, event: str, **kwargs: Any) -> None:
        """Record a timestamped event in this agent's activity log.

        event   short verb like 'fork', 'write', 'merge', 'github_fetch'
        kwargs  any structured payload — kept JSON-serialisable
        """
        self._step_counter += 1
        entry: Dict[str, Any] = {
            "step":   self._step_counter,
            "t_ms":   int((time.time() - self._t_start) * 1000),
            "event":  event,
            "agent":  self.agent_id,
        }
        for k, v in kwargs.items():
            if isinstance(v, (str, int, float, bool)) or v is None:
                entry[k] = v
            elif isinstance(v, (list, dict)):
                entry[k] = v
            else:
                entry[k] = str(v)
        self.activity.append(entry)

    async def flush_activity_log(self, branch: str = "main") -> Dict:
        """Persist this agent's activity log to AgentSkein.

        Key:   activity-{agent_id}     (unique per agent → no merge conflicts)
        Value: {agent, count, events:[...]}
        Strategy: last_write_wins (idempotent within a single run).
        """
        return await self.write(
            f"activity-{self.agent_id}",
            {
                "agent":  self.agent_id,
                "count":  len(self.activity),
                "events": self.activity,
            },
            branch=branch,
            strategy="last_write_wins",
        )

    async def init_namespace(self, description: Optional[str] = None) -> bool:
        url = f"{self.base_url}/namespace/{self.namespace}/init"
        body = {"agent_id": self.agent_id}
        if description:
            body["description"] = description

        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                response = await client.post(url, json=body)
                response.raise_for_status()
                data = response.json()
                return data.get("success", False)
        except Exception as e:
            self.errors.append(f"Init namespace failed: {str(e)}")
            return False

    async def write(self, key: str, value: Any, branch: str = "main",
                    strategy: str = "merge_structural") -> Dict:
        url = f"{self.base_url}/namespace/{self.namespace}/write/{key}"
        body = {
            "agent_id": self.agent_id,
            "value": value,
            "branch": branch,
            "conflict_strategy": strategy
        }

        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                response = await client.post(url, json=body)
                if response.status_code == 409:
                    return response.json()
                response.raise_for_status()
                return response.json()
        except Exception as e:
            self.errors.append(f"Write failed ({key}): {str(e)}")
            return {"success": False, "error": str(e)}

    async def read(self, key: str, branch: str = "main") -> Any:
        url = f"{self.base_url}/namespace/{self.namespace}/read/{key}"
        params = {"agent_id": self.agent_id, "branch": branch}

        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                response = await client.get(url, params=params)
                response.raise_for_status()
                data = response.json()
                return data.get("value") if data.get("found") else None
        except Exception as e:
            self.errors.append(f"Read failed ({key}): {str(e)}")
            return None

    async def snapshot(self, branch: str = "main") -> Dict:
        url = f"{self.base_url}/namespace/{self.namespace}/snapshot"
        params = {"agent_id": self.agent_id, "branch": branch}

        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                response = await client.get(url, params=params)
                response.raise_for_status()
                return response.json()
        except Exception as e:
            self.errors.append(f"Snapshot failed: {str(e)}")
            return {"data": {}}

    async def fork(self, branch_name: str, from_branch: str = "main") -> bool:
        url = f"{self.base_url}/namespace/{self.namespace}/fork"
        body = {
            "agent_id": self.agent_id,
            "branch_name": branch_name,
            "from_branch": from_branch
        }

        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                response = await client.post(url, json=body)
                response.raise_for_status()
                data = response.json()
                return data.get("success", False)
        except Exception as e:
            self.errors.append(f"Fork failed: {str(e)}")
            return False

    async def merge(self, from_branch: str, to_branch: str = "main",
                    strategy: str = "merge_structural") -> Dict:
        url = f"{self.base_url}/namespace/{self.namespace}/merge"
        body = {
            "agent_id": self.agent_id,
            "from_branch": from_branch,
            "to_branch": to_branch,
            "conflict_strategy": strategy
        }

        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                response = await client.post(url, json=body)
                response.raise_for_status()
                return response.json()
        except Exception as e:
            self.errors.append(f"Merge failed ({from_branch} -> {to_branch}): {str(e)}")
            return {"success": False, "error": str(e)}

    async def check_poison(self, key: str, value: Any) -> Dict:
        url = f"{self.base_url}/detect-poisoning"
        body = {
            "agent_id": self.agent_id,
            "namespace": self.namespace,
            "key": key,
            "value": value
        }

        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                response = await client.post(url, json=body)
                response.raise_for_status()
                return response.json()
        except Exception as e:
            self.errors.append(f"Poison check failed: {str(e)}")
            return {"safe": True, "error": str(e)}

    async def delete_key(self, key: str) -> bool:
        url = f"{self.base_url}/namespace/{self.namespace}/key/{key}"
        params = {"agent_id": self.agent_id}
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                response = await client.delete(url, params=params)
                response.raise_for_status()
                return response.json().get("success", False)
        except Exception as e:
            self.errors.append(f"Delete key failed ({key}): {str(e)}")
            return False

    async def run(self) -> Dict:
        raise NotImplementedError("Subclasses must implement run()")
