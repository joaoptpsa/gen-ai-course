"""A small persistent memory store for agents (Session 4 onwards).

This is supplied storage, not a memory policy. It stores records in a SQLite
file and offers basic queries. What is written, by whom, with which
confidence, how conflicts are resolved and what is returned to the model is
decided by the harness.

A record:

    memory_id     unique id (MEM-0001, ...)
    kind          free text, e.g. known_issue, incident_summary, shift_note, procedure
    subject       usually a component name, e.g. order-gateway
    content       the text of the memory
    source_type   who or what produced it: user | agent | tool | document
    source_ref    where it came from (ticket key, run id, log ref, user name)
    author        identity that wrote it
    team          isolation scope: records are only visible to the same team
    created_at    simulated date and time, e.g. "2026-11-04 10:05"
    valid_until   optional date and time after which the record is stale
    confidence    0.0 to 1.0, set by the writer
    status        active | superseded
    supersedes    memory_id of the record this one corrects, if any

Deleting a record removes its content. Only the id, the time and the reason
are kept in a deletion log, so a deletion can be audited without keeping the
deleted information.
"""

from __future__ import annotations

import sqlite3
from collections.abc import Generator
from contextlib import closing, contextmanager
from dataclasses import asdict, dataclass, fields
from pathlib import Path
from typing import Any

SOURCE_TYPES = ("user", "agent", "tool", "document")


@dataclass
class MemoryRecord:
    memory_id: str
    kind: str
    subject: str
    content: str
    source_type: str
    source_ref: str
    author: str
    team: str
    created_at: str
    valid_until: str | None = None
    confidence: float = 0.5
    status: str = "active"
    supersedes: str | None = None

    def public(self) -> dict[str, Any]:
        return asdict(self)


_COLUMNS = [field.name for field in fields(MemoryRecord)]


class MemoryStore:
    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with closing(self._connect()) as connection, connection:
            connection.execute(
                "CREATE TABLE IF NOT EXISTS memories ("
                "memory_id TEXT PRIMARY KEY, kind TEXT, subject TEXT, content TEXT, source_type TEXT, source_ref TEXT, "
                "author TEXT, team TEXT, created_at TEXT, valid_until TEXT, confidence REAL, status TEXT, supersedes TEXT)"
            )
            connection.execute(
                "CREATE TABLE IF NOT EXISTS deletions (memory_id TEXT, deleted_at TEXT, deleted_by TEXT, reason TEXT)"
            )

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.path)
        connection.row_factory = sqlite3.Row
        return connection

    def _next_id(self, connection: sqlite3.Connection) -> str:
        count = connection.execute("SELECT COUNT(*) FROM memories").fetchone()[0]
        deleted = connection.execute("SELECT COUNT(*) FROM deletions").fetchone()[0]
        number = count + deleted + 1
        while connection.execute(
            "SELECT 1 FROM memories WHERE memory_id = ?", (f"MEM-{number:04d}",)
        ).fetchone():
            number += 1
        return f"MEM-{number:04d}"

    @contextmanager
    def transaction(self) -> Generator[sqlite3.Connection]:
        """One connection whose writes, including `add_within`, commit or roll back together."""
        with closing(self._connect()) as connection, connection:
            yield connection

    # Writing ---------------------------------------------------------------

    def add(
        self,
        *,
        kind: str,
        subject: str,
        content: str,
        source_type: str,
        source_ref: str,
        author: str,
        team: str,
        created_at: str,
        valid_until: str | None = None,
        confidence: float = 0.5,
        supersedes: str | None = None,
        memory_id: str | None = None,
    ) -> MemoryRecord:
        with self.transaction() as connection:
            record = self.add_within(
                connection,
                kind=kind,
                subject=subject,
                content=content,
                source_type=source_type,
                source_ref=source_ref,
                author=author,
                team=team,
                created_at=created_at,
                valid_until=valid_until,
                confidence=confidence,
                supersedes=supersedes,
                memory_id=memory_id,
            )
        return record

    def add_within(
        self,
        connection: sqlite3.Connection,
        *,
        kind: str,
        subject: str,
        content: str,
        source_type: str,
        source_ref: str,
        author: str,
        team: str,
        created_at: str,
        valid_until: str | None = None,
        confidence: float = 0.5,
        supersedes: str | None = None,
        memory_id: str | None = None,
    ) -> MemoryRecord:
        """Add a memory inside a caller's `transaction()`, so it commits with the caller's other writes."""
        if source_type not in SOURCE_TYPES:
            raise ValueError(f"source_type must be one of {SOURCE_TYPES}")
        record = MemoryRecord(
            memory_id="",
            kind=kind,
            subject=subject,
            content=content,
            source_type=source_type,
            source_ref=source_ref,
            author=author,
            team=team,
            created_at=created_at,
            valid_until=valid_until,
            confidence=max(0.0, min(1.0, float(confidence))),
            supersedes=supersedes,
        )
        self._insert(connection, record, memory_id)
        return record

    def _insert(
        self,
        connection: sqlite3.Connection,
        record: MemoryRecord,
        memory_id: str | None,
    ) -> None:
        record.memory_id = memory_id or self._next_id(connection)
        placeholders = ", ".join("?" for _ in _COLUMNS)
        connection.execute(
            f"INSERT OR IGNORE INTO memories ({', '.join(_COLUMNS)}) VALUES ({placeholders})",
            [getattr(record, name) for name in _COLUMNS],
        )
        if record.supersedes:
            connection.execute(
                "UPDATE memories SET status = 'superseded' WHERE memory_id = ?",
                (record.supersedes,),
            )

    def update(self, memory_id: str, **changes: Any) -> MemoryRecord:
        unknown = set(changes) - set(_COLUMNS) - {"memory_id"}
        if unknown:
            raise ValueError(f"Unknown fields: {sorted(unknown)}")
        changes.pop("memory_id", None)
        if changes:
            with closing(self._connect()) as connection, connection:
                assignments = ", ".join(f"{name} = ?" for name in changes)
                connection.execute(
                    f"UPDATE memories SET {assignments} WHERE memory_id = ?",
                    [*changes.values(), memory_id],
                )
        return self.get(memory_id)

    def delete(
        self, memory_id: str, *, deleted_at: str, deleted_by: str, reason: str
    ) -> bool:
        with closing(self._connect()) as connection, connection:
            removed = connection.execute(
                "DELETE FROM memories WHERE memory_id = ?", (memory_id,)
            ).rowcount
            if removed:
                connection.execute(
                    "INSERT INTO deletions VALUES (?, ?, ?, ?)",
                    (memory_id, deleted_at, deleted_by, reason),
                )
        return bool(removed)

    # Reading ---------------------------------------------------------------

    def get(self, memory_id: str) -> MemoryRecord:
        with closing(self._connect()) as connection:
            row = connection.execute(
                "SELECT * FROM memories WHERE memory_id = ?", (memory_id,)
            ).fetchone()
        if row is None:
            raise KeyError(f"Unknown memory: {memory_id}")
        return MemoryRecord(**dict(row))

    def search(
        self,
        *,
        text: str | None = None,
        subject: str | None = None,
        kind: str | None = None,
        team: str | None = None,
        source_types: list[str] | None = None,
        min_confidence: float | None = None,
        include_superseded: bool = False,
        limit: int = 50,
    ) -> list[MemoryRecord]:
        """Basic filters. `text` matches any of its words in the content (case-insensitive)."""
        query, params = "SELECT * FROM memories WHERE 1 = 1", []
        if subject is not None:
            query += " AND subject = ?"
            params.append(subject)
        if kind is not None:
            query += " AND kind = ?"
            params.append(kind)
        if team is not None:
            query += " AND team = ?"
            params.append(team)
        if source_types:
            query += f" AND source_type IN ({', '.join('?' for _ in source_types)})"
            params.extend(source_types)
        if min_confidence is not None:
            query += " AND confidence >= ?"
            params.append(min_confidence)
        if not include_superseded:
            query += " AND status = 'active'"
        words = [word for word in (text or "").lower().split() if len(word) > 2]
        if words:
            query += (
                " AND (" + " OR ".join("LOWER(content) LIKE ?" for _ in words) + ")"
            )
            params.extend(f"%{word}%" for word in words)
        query += " ORDER BY created_at DESC LIMIT ?"
        params.append(limit)
        with closing(self._connect()) as connection:
            rows = connection.execute(query, params).fetchall()
        return [MemoryRecord(**dict(row)) for row in rows]

    def all(self) -> list[MemoryRecord]:
        return self.search(include_superseded=True, limit=100_000)

    def deletions(self) -> list[dict[str, Any]]:
        with closing(self._connect()) as connection:
            return [
                dict(row)
                for row in connection.execute("SELECT * FROM deletions").fetchall()
            ]

    def seed(self, records: list[dict[str, Any]]) -> None:
        """Add records from a scenario (memories from earlier shifts). Existing ids are kept."""
        for record in records:
            self.add(**record)
