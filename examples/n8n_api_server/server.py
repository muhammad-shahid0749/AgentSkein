"""
AgentSkein REST API Server
==========================
Wraps AgentSkein in a FastAPI HTTP service so that ANY tool that can
make HTTP requests — n8n, Make, Zapier, custom agents, curl — can use
AgentSkein shared memory with full conflict resolution.

Start the server:
    cd agentskein/
    uvicorn examples.n8n_api_server.server:app --host 0.0.0.0 --port 8765 --reload

Or directly:
    python examples/n8n_api_server/server.py

Then call it from n8n using the HTTP Request node.

API endpoints:
    POST /namespace/{ns}/init          Create or initialise a namespace
    POST /namespace/{ns}/write         Write a key-value pair
    GET  /namespace/{ns}/read/{key}    Read a single key
    GET  /namespace/{ns}/snapshot      Read all keys
    GET  /namespace/{ns}/keys          List all keys
    POST /namespace/{ns}/fork          Fork a new branch
    POST /namespace/{ns}/merge         Merge a branch into another
    GET  /namespace/{ns}/branches      List all branches
    DELETE /namespace/{ns}/key/{key}   Delete a key
    GET  /health                       Health check
    POST /detect-poisoning             Check a value for injection attacks
"""
import sys
import os

# Make AgentSkein importable whether installed or run from source
_root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if _root not in sys.path:
    sys.path.insert(0, _root)

import enum
if not hasattr(enum, "StrEnum"):
    class StrEnum(str, enum.Enum):
        pass
    enum.StrEnum = StrEnum

import asyncio
from typing import Any, Optional
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from agentskein import AgentSkein, ConflictStrategy
from agentskein.storage.memory_backend import InMemoryBackend
from agentskein.protocol.poisoning import PoisoningDetector

# ── Choose backend ────────────────────────────────────────────────────────────
REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379/0")
USE_REDIS  = os.getenv("USE_REDIS", "auto")   # "auto", "true", "false"
SQLITE_PATH = os.getenv("SQLITE_PATH", "")    # set to use SQLite

def build_backend():
    if SQLITE_PATH:
        from agentskein.storage.sqlite_backend import SQLiteBackend
        print(f"[AgentSkein] Using SQLite backend: {SQLITE_PATH}")
        return SQLiteBackend(SQLITE_PATH)

    if USE_REDIS in ("true", "auto"):
        try:
            import redis as _r
            _r.Redis.from_url(REDIS_URL, socket_connect_timeout=1).ping()
            from agentskein.storage.redis_backend import RedisBackend
            print(f"[AgentSkein] Using Redis backend: {REDIS_URL}")
            return RedisBackend(REDIS_URL)
        except Exception:
            if USE_REDIS == "true":
                raise RuntimeError(f"Redis not reachable at {REDIS_URL}")

    print("[AgentSkein] Using InMemory backend (data lost on restart)")
    return InMemoryBackend()


# ── Global state ──────────────────────────────────────────────────────────────
_backend = None
_poisoning_detector = PoisoningDetector()

@asynccontextmanager
async def lifespan(app: FastAPI):
    global _backend
    _backend = build_backend()
    print("[AgentSkein API] Server ready.")
    yield
    if hasattr(_backend, "close"):
        await _backend.close()


app = FastAPI(
    title="AgentSkein REST API",
    description=(
        "HTTP wrapper around AgentSkein shared agent memory. "
        "Use from n8n, Make, Zapier, or any HTTP client."
    ),
    version="0.1.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


# ── Request / Response models ─────────────────────────────────────────────────

class WriteRequest(BaseModel):
    agent_id: str
    value: Any
    branch: str = "main"
    conflict_strategy: str = "merge_structural"
    tags: list[str] = []
    ttl_seconds: Optional[int] = None

class InitRequest(BaseModel):
    agent_id: str = "system"
    description: str = ""

class ForkRequest(BaseModel):
    agent_id: str
    branch_name: str
    from_branch: str = "main"

class MergeRequest(BaseModel):
    agent_id: str
    from_branch: str
    to_branch: str = "main"
    conflict_strategy: str = "merge_structural"

class PoisonCheckRequest(BaseModel):
    agent_id: str
    namespace: str
    key: str
    value: Any

class WriteResponse(BaseModel):
    success: bool
    key: str
    namespace: str
    branch: str
    agent_id: str
    conflict_detected: bool = False
    conflict_resolved_by: Optional[str] = None
    entry_id: Optional[str] = None

class ReadResponse(BaseModel):
    key: str
    value: Any
    namespace: str
    branch: str
    agent_id: Optional[str] = None
    found: bool


def _strategy(s: str) -> ConflictStrategy:
    mapping = {
        "last_write_wins":  ConflictStrategy.LAST_WRITE_WINS,
        "first_write_wins": ConflictStrategy.FIRST_WRITE_WINS,
        "merge_structural":  ConflictStrategy.MERGE_STRUCTURAL,
        "merge_semantic":    ConflictStrategy.MERGE_SEMANTIC,
        "raise":             ConflictStrategy.RAISE,
    }
    if s not in mapping:
        raise HTTPException(400, f"Unknown conflict_strategy '{s}'. "
                            f"Choose from: {list(mapping.keys())}")
    return mapping[s]


def _mesh(agent_id: str, namespace: str, branch: str = "main",
          strategy: str = "merge_structural") -> AgentSkein:
    return AgentSkein(
        agent_id=agent_id,
        namespace=namespace,
        branch=branch,
        backend=_backend,
        conflict_strategy=_strategy(strategy),
    )


# ── Endpoints ─────────────────────────────────────────────────────────────────

@app.get("/health")
async def health():
    """Health check. Returns backend type."""
    return {
        "status": "ok",
        "backend": type(_backend).__name__,
        "redis_url": REDIS_URL if "Redis" in type(_backend).__name__ else None,
    }


@app.post("/namespace/{ns}/init")
async def init_namespace(ns: str, body: InitRequest):
    """Create namespace if it doesn't exist. Safe to call multiple times."""
    mesh = _mesh(body.agent_id, ns)
    await mesh.init()
    return {"success": True, "namespace": ns, "agent_id": body.agent_id}


@app.post("/namespace/{ns}/write/{key}", response_model=WriteResponse)
async def write_key(ns: str, key: str, body: WriteRequest):
    """
    Write a value to shared memory.

    n8n example (HTTP Request node):
      Method: POST
      URL:    http://localhost:8765/namespace/my-task/write/result
      Body (JSON):
        {
          "agent_id": "researcher-1",
          "value":    {"finding": "CRDT clocks work well", "confidence": 0.9},
          "branch":   "main",
          "conflict_strategy": "merge_structural"
        }
    """
    # Optional poisoning check before write
    alerts = _poisoning_detector.check(body.agent_id, ns, key, body.value)
    if alerts and alerts[0].severity == "high":
        raise HTTPException(
            status_code=422,
            detail={
                "error": "Potential prompt injection detected in value",
                "reason": alerts[0].reason,
                "severity": alerts[0].severity,
            }
        )

    mesh = _mesh(body.agent_id, ns, body.branch, body.conflict_strategy)
    await mesh.init()

    conflict_detected = False
    conflict_resolved_by = None

    try:
        from agentskein.client import ConflictDetectedError
        entry = await mesh.write(
            key, body.value,
            tags=body.tags,
            ttl_seconds=body.ttl_seconds,
        )
        return WriteResponse(
            success=True,
            key=key,
            namespace=ns,
            branch=body.branch,
            agent_id=body.agent_id,
            conflict_detected=conflict_detected,
            conflict_resolved_by=conflict_resolved_by,
            entry_id=entry.id,
        )
    except Exception as e:
        if "ConflictDetectedError" in type(e).__name__:
            raise HTTPException(
                status_code=409,
                detail={
                    "error": "Write conflict detected (strategy=raise)",
                    "key": key,
                    "our_value":   e.conflict.entry_ours.value,
                    "their_value": e.conflict.entry_theirs.value,
                    "hint": "Retry with a different conflict_strategy or resolve manually.",
                }
            )
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/namespace/{ns}/read/{key}", response_model=ReadResponse)
async def read_key(
    ns: str,
    key: str,
    agent_id: str = Query(default="api-reader"),
    branch: str   = Query(default="main"),
):
    """
    Read a value from shared memory.

    n8n example (HTTP Request node):
      Method: GET
      URL:    http://localhost:8765/namespace/my-task/read/result?agent_id=writer-1
    """
    mesh = _mesh(agent_id, ns, branch)
    await mesh.init()
    entry = await mesh.read_entry(key)
    if entry is None:
        return ReadResponse(key=key, value=None, namespace=ns,
                            branch=branch, found=False)
    return ReadResponse(
        key=key, value=entry.value, namespace=ns,
        branch=branch, agent_id=entry.agent_id, found=True,
    )


@app.get("/namespace/{ns}/snapshot")
async def snapshot(
    ns: str,
    agent_id: str = Query(default="api-reader"),
    branch: str   = Query(default="main"),
):
    """
    Return ALL key-value pairs in the namespace.

    n8n example: GET http://localhost:8765/namespace/my-task/snapshot
    Returns a dict you can loop over with a Split node.
    """
    mesh = _mesh(agent_id, ns, branch)
    await mesh.init()
    data = await mesh.snapshot()
    return {"namespace": ns, "branch": branch, "count": len(data), "data": data}


@app.get("/namespace/{ns}/keys")
async def list_keys(
    ns: str,
    agent_id: str = Query(default="api-reader"),
    branch: str   = Query(default="main"),
):
    """List all keys in the namespace."""
    mesh = _mesh(agent_id, ns, branch)
    await mesh.init()
    keys = await mesh.list_keys()
    return {"namespace": ns, "branch": branch, "keys": keys, "count": len(keys)}


@app.post("/namespace/{ns}/fork")
async def fork_branch(ns: str, body: ForkRequest):
    """
    Fork a new branch from an existing branch (O(1), no data copy).

    n8n example: POST http://localhost:8765/namespace/my-task/fork
    Body: {"agent_id": "worker-1", "branch_name": "worker-1-branch", "from_branch": "main"}
    """
    mesh = _mesh(body.agent_id, ns, body.from_branch)
    await mesh.init()
    forked = await mesh.fork(body.branch_name)
    return {
        "success": True,
        "namespace": ns,
        "new_branch": body.branch_name,
        "parent_branch": body.from_branch,
        "agent_id": body.agent_id,
    }


@app.post("/namespace/{ns}/merge")
async def merge_branch(ns: str, body: MergeRequest):
    """
    Merge a branch into another (usually into 'main').

    n8n example: POST http://localhost:8765/namespace/my-task/merge
    Body: {"agent_id": "worker-1", "from_branch": "worker-1-branch", "to_branch": "main"}
    """
    mesh = _mesh(body.agent_id, ns, body.from_branch, body.conflict_strategy)
    await mesh.init()
    summary = await mesh.merge_to(body.to_branch)
    return {
        "success": True,
        "namespace": ns,
        "from_branch": body.from_branch,
        "to_branch": body.to_branch,
        "merged_keys": summary["merged_keys"],
        "conflict_keys": summary["conflict_keys"],
        "merged_count": len(summary["merged_keys"]),
        "conflict_count": len(summary["conflict_keys"]),
    }


@app.get("/namespace/{ns}/branches")
async def list_branches(ns: str):
    """List all branches in a namespace."""
    state = await _backend.get_namespace(ns)
    if state is None:
        raise HTTPException(404, f"Namespace '{ns}' not found")
    branches = [
        {
            "name":          b.name,
            "parent_branch": b.parent_branch,
            "created_by":    b.created_by,
            "is_merged":     b.is_merged,
        }
        for b in state.branches.values()
    ]
    return {"namespace": ns, "branches": branches, "count": len(branches)}


@app.delete("/namespace/{ns}/key/{key}")
async def delete_key(
    ns: str,
    key: str,
    agent_id: str = Query(default="api-deleter"),
    branch: str   = Query(default="main"),
):
    """Delete a key from the namespace."""
    mesh = _mesh(agent_id, ns, branch)
    await mesh.init()
    deleted = await mesh.delete(key)
    return {"success": deleted, "key": key, "namespace": ns}


@app.post("/detect-poisoning")
async def detect_poisoning(body: PoisonCheckRequest):
    """
    Check a value for prompt injection or overwrite storm patterns.
    Call this before writing sensitive values.
    """
    alerts = _poisoning_detector.check(
        body.agent_id, body.namespace, body.key, body.value
    )
    return {
        "safe": len(alerts) == 0,
        "alert_count": len(alerts),
        "alerts": [
            {
                "reason":   a.reason,
                "severity": a.severity,
                "snippet":  a.value_snippet,
            }
            for a in alerts
        ],
    }


# ── Run directly ──────────────────────────────────────────────────────────────
if __name__ == "__main__":
    import uvicorn
    port = int(os.getenv("PORT", 8765))
    print(f"\n  AgentSkein API Server starting on http://0.0.0.0:{port}")
    print(f"  Swagger UI: http://localhost:{port}/docs")
    print(f"  ReDoc:      http://localhost:{port}/redoc\n")
    uvicorn.run(
        "examples.n8n_api_server.server:app",
        host="0.0.0.0",
        port=port,
        reload=True,
        reload_dirs=[_root],
    )
