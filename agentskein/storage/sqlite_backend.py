"""
SQLite storage backend. [B9]
Uses aiosqlite for non-blocking I/O.
No external services needed — good for local dev and CI without Docker.

Schema:
  namespaces(name TEXT PK, data TEXT)
  entries(namespace TEXT, branch TEXT, key TEXT, data TEXT, created_at REAL,
          PRIMARY KEY (namespace, branch, key))
  branches(namespace TEXT, name TEXT, data TEXT,
           PRIMARY KEY (namespace, name))
  locks(resource TEXT PK, token TEXT)

[B3] get_entry() implements lazy copy-on-write fall-through to parent branch.
"""
from __future__ import annotations

import secrets

import aiosqlite

from ..protocol.namespace import NamespaceState
from ..protocol.types import Branch, MemoryEntry

_DDL = """
CREATE TABLE IF NOT EXISTS namespaces (name TEXT PRIMARY KEY, data TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS entries (
    namespace  TEXT NOT NULL,
    branch     TEXT NOT NULL,
    key        TEXT NOT NULL,
    data       TEXT NOT NULL,
    created_at REAL NOT NULL,
    PRIMARY KEY (namespace, branch, key)
);
CREATE TABLE IF NOT EXISTS branches (
    namespace TEXT NOT NULL,
    name      TEXT NOT NULL,
    data      TEXT NOT NULL,
    PRIMARY KEY (namespace, name)
);
CREATE TABLE IF NOT EXISTS locks (
    resource TEXT PRIMARY KEY,
    token    TEXT NOT NULL
);
"""


class SQLiteBackend:
    def __init__(self, db_path: str = "agentskein.db"):
        self._path = db_path
        self._db: aiosqlite.Connection | None = None

    async def _conn(self) -> aiosqlite.Connection:
        if self._db is None:
            self._db = await aiosqlite.connect(self._path)
            self._db.row_factory = aiosqlite.Row
            await self._db.executescript(_DDL)
            await self._db.commit()
        return self._db

    # ── Namespace ──────────────────────────────────────────────────────────────

    async def get_namespace(self, name: str) -> NamespaceState | None:
        db = await self._conn()
        async with db.execute("SELECT data FROM namespaces WHERE name=?", (name,)) as cur:
            row = await cur.fetchone()
        return NamespaceState.model_validate_json(row["data"]) if row else None

    async def save_namespace(self, state: NamespaceState) -> None:
        db = await self._conn()
        await db.execute(
            "INSERT OR REPLACE INTO namespaces VALUES (?,?)",
            (state.config.name, state.model_dump_json()),
        )
        await db.commit()

    # ── Entries ────────────────────────────────────────────────────────────────

    async def get_entry(self, namespace: str, branch: str, key: str) -> MemoryEntry | None:
        db = await self._conn()
        async with db.execute(
            "SELECT data FROM entries WHERE namespace=? AND branch=? AND key=?",
            (namespace, branch, key),
        ) as cur:
            row = await cur.fetchone()
        if row:
            return MemoryEntry.model_validate_json(row["data"])
        # [B3] Lazy CoW fall-through to parent branch
        parent = await self.get_branch(namespace, branch)
        if parent and parent.parent_branch and parent.parent_branch != branch:
            return await self.get_entry(namespace, parent.parent_branch, key)
        return None

    async def save_entry(self, entry: MemoryEntry) -> None:
        db = await self._conn()
        await db.execute(
            "INSERT OR REPLACE INTO entries VALUES (?,?,?,?,?)",
            (entry.namespace, entry.branch, entry.key,
             entry.model_dump_json(), entry.created_at),
        )
        await db.commit()

    async def get_branch_entries(self, namespace: str, branch: str) -> list[MemoryEntry]:
        db = await self._conn()
        async with db.execute(
            "SELECT data FROM entries WHERE namespace=? AND branch=? ORDER BY created_at",
            (namespace, branch),
        ) as cur:
            rows = await cur.fetchall()
        return [MemoryEntry.model_validate_json(r["data"]) for r in rows]

    async def delete_entry(self, namespace: str, branch: str, key: str) -> bool:
        db = await self._conn()
        async with db.execute(
            "DELETE FROM entries WHERE namespace=? AND branch=? AND key=?",
            (namespace, branch, key),
        ) as cur:
            deleted = cur.rowcount > 0
        await db.commit()
        return deleted

    # ── Branches ───────────────────────────────────────────────────────────────

    async def get_branch(self, namespace: str, branch_name: str) -> Branch | None:
        db = await self._conn()
        async with db.execute(
            "SELECT data FROM branches WHERE namespace=? AND name=?",
            (namespace, branch_name),
        ) as cur:
            row = await cur.fetchone()
        return Branch.model_validate_json(row["data"]) if row else None

    async def save_branch(self, namespace: str, branch: Branch) -> None:
        db = await self._conn()
        await db.execute(
            "INSERT OR REPLACE INTO branches VALUES (?,?,?)",
            (namespace, branch.name, branch.model_dump_json()),
        )
        await db.commit()

    # ── Locking ────────────────────────────────────────────────────────────────

    async def acquire_lock(self, resource: str, ttl_ms: int = 2000) -> str | None:
        db = await self._conn()
        token = secrets.token_hex(16)
        try:
            await db.execute("INSERT INTO locks VALUES (?,?)", (resource, token))
            await db.commit()
            return token
        except aiosqlite.IntegrityError:
            return None

    async def release_lock(self, resource: str, token: str) -> bool:
        db = await self._conn()
        async with db.execute(
            "DELETE FROM locks WHERE resource=? AND token=?", (resource, token)
        ) as cur:
            deleted = cur.rowcount > 0
        await db.commit()
        return deleted

    async def close(self) -> None:
        if self._db:
            await self._db.close()
            self._db = None
