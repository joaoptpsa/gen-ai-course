"""Lessons the team learns between incidents, kept per role in the memory store.

A lesson is a `MemoryRecord` of kind `lesson`. Its `team` field holds the role that owns it, so
network's lessons never reach database. Team-wide knowledge reaches a role only inside a handoff the
orchestrator records. `source_ref` holds the origin run, and `confidence` and `valid_until` keep
their usual meaning.

After an incident is evaluated, `record_lesson_outcome` settles the lessons that run used. Each
settlement is written in the same transaction as the memory change and is keyed by (run, lesson),
so replaying it changes nothing. A memory file used for a fair comparison is copied with
`snapshot_memory`, which disables learning on the copy.

Errors follow `meridian/memory.py`: unknown ids raise `KeyError`, bad values raise `ValueError`.
"""

from __future__ import annotations

import hashlib
import json
import sqlite3
from contextlib import closing
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, Field

from meridian.memory import MemoryRecord, MemoryStore

LESSON_KIND = "lesson"
ANY_SUBJECT = "*"
CONFIRMATION_STEP = 0.2

Outcome = Literal["passed", "failed", "unevaluated"]
Action = Literal["created", "confirmed", "superseded", "retired"]

_TABLES = (
    (
        "CREATE TABLE IF NOT EXISTS lesson_events ("
        "run_id TEXT, lesson_key TEXT, action TEXT, memory_id TEXT, result_id TEXT, settled_at TEXT, evidence TEXT, "
        "PRIMARY KEY (run_id, lesson_key))"
    ),
    "CREATE TABLE IF NOT EXISTS lesson_frozen (frozen INTEGER)",
)
_FINGERPRINT_QUERIES = (
    "SELECT * FROM memories ORDER BY memory_id",
    "SELECT * FROM deletions ORDER BY memory_id, deleted_at",
    "SELECT * FROM lesson_events ORDER BY run_id, lesson_key",
)


class Lesson(BaseModel):
    lesson_id: str
    role: str
    subject: str
    text: str
    origin_run: str
    confidence: float
    created_at: str
    valid_until: str | None = None
    supersedes: str | None = None


class LessonDraft(BaseModel):
    """A lesson an agent proposes after an incident."""

    role: str
    subject: str
    text: str
    confidence: float = 0.5
    valid_until: str | None = None
    created_at: str


class LessonUse(BaseModel):
    """A lesson a role cited in a handoff or decision, with the evidence for the citation.

    `implicated` marks a lesson behind a failing decision. A correction needs its own evidence to
    supersede the lesson; without both, the lesson is retired.
    """

    role: str
    lesson_id: str
    handoff_id: str = ""
    evidence_refs: list[str] = Field(default_factory=list)
    implicated: bool = False
    correction: str = ""
    correction_evidence: list[str] = Field(default_factory=list)


class LessonUpdate(BaseModel):
    run_id: str
    lesson_id: str
    action: Action
    result_id: str
    evidence_refs: list[str] = Field(default_factory=list)


# Recall -------------------------------------------------------------------------------------


def lesson_from_record(record: MemoryRecord) -> Lesson:
    return Lesson(
        lesson_id=record.memory_id,
        role=record.team,
        subject=record.subject,
        text=record.content,
        origin_run=record.source_ref,
        confidence=record.confidence,
        created_at=record.created_at,
        valid_until=record.valid_until,
        supersedes=record.supersedes,
    )


def recall_lessons(
    store: MemoryStore, role: str, subject: str, at: str
) -> list[Lesson]:
    """Active lessons of exactly this role, for this subject, valid at the simulated time `at`."""
    records = store.search(kind=LESSON_KIND, team=role, limit=100_000)
    applicable = [
        record
        for record in records
        if record.subject in (subject, ANY_SUBJECT) and _valid_at(record, at)
    ]
    ranked = sorted(
        applicable, key=lambda record: (-record.confidence, record.memory_id)
    )
    return [lesson_from_record(record) for record in ranked]


def _valid_at(record: MemoryRecord, at: str) -> bool:
    if record.created_at > at:
        return False
    expired = record.valid_until is not None and record.valid_until < at
    return not expired


# Settlement ---------------------------------------------------------------------------------


def record_lesson_outcome(
    store: MemoryStore,
    run_id: str,
    outcome: Outcome,
    uses: list[LessonUse],
    drafts: list[LessonDraft],
    *,
    at: str,
) -> list[LessonUpdate]:
    """Settle one evaluated run. Replaying the same run returns an empty list and changes nothing.

    passed: lessons the run used gain confidence. failed: implicated lessons are superseded by an
    evidence-backed correction or retired; other lessons stay as they are. unevaluated: nothing is
    settled. Drafts become new lessons unless the store is a frozen snapshot.
    """
    if outcome == "unevaluated" or is_frozen(store.path):
        return []
    updates: list[LessonUpdate] = []
    with store.transaction() as connection:
        for statement in _TABLES:
            connection.execute(statement)
        for use in uses:
            update = _settle_use(store, connection, run_id, outcome, use, at)
            if update is not None:
                updates.append(update)
        for draft in drafts:
            update = _settle_draft(store, connection, run_id, draft, at)
            if update is not None:
                updates.append(update)
    return updates


def _claim(
    connection: sqlite3.Connection,
    run_id: str,
    key: str,
    action: Action,
    memory_id: str,
    result_id: str,
    at: str,
    evidence: list[str],
) -> bool:
    """Record the settlement; false when this run already settled this key."""
    cursor = connection.execute(
        "INSERT OR IGNORE INTO lesson_events VALUES (?, ?, ?, ?, ?, ?, ?)",
        (run_id, key, action, memory_id, result_id, at, json.dumps(evidence)),
    )
    return cursor.rowcount == 1


def _active_lesson(
    connection: sqlite3.Connection, use: LessonUse
) -> MemoryRecord | None:
    row = connection.execute(
        "SELECT * FROM memories WHERE memory_id = ? AND kind = ? AND team = ? AND status = 'active'",
        (use.lesson_id, LESSON_KIND, use.role),
    ).fetchone()
    return None if row is None else MemoryRecord(**dict(row))


def _settle_use(
    store: MemoryStore,
    connection: sqlite3.Connection,
    run_id: str,
    outcome: Outcome,
    use: LessonUse,
    at: str,
) -> LessonUpdate | None:
    lesson = _active_lesson(connection, use)
    if lesson is None:
        return None
    if outcome == "passed":
        return _confirm(connection, run_id, lesson, use, at)
    if not use.implicated:
        return None
    if use.correction and use.correction_evidence:
        return _supersede(store, connection, run_id, lesson, use, at)
    return _retire(connection, run_id, lesson, use, at)


def _confirm(
    connection: sqlite3.Connection,
    run_id: str,
    lesson: MemoryRecord,
    use: LessonUse,
    at: str,
) -> LessonUpdate | None:
    if not _claim(
        connection,
        run_id,
        lesson.memory_id,
        "confirmed",
        lesson.memory_id,
        lesson.memory_id,
        at,
        use.evidence_refs,
    ):
        return None
    confidence = min(
        1.0, lesson.confidence + (1.0 - lesson.confidence) * CONFIRMATION_STEP
    )
    connection.execute(
        "UPDATE memories SET confidence = ? WHERE memory_id = ?",
        (confidence, lesson.memory_id),
    )
    return LessonUpdate(
        run_id=run_id,
        lesson_id=lesson.memory_id,
        action="confirmed",
        result_id=lesson.memory_id,
        evidence_refs=use.evidence_refs,
    )


def _supersede(
    store: MemoryStore,
    connection: sqlite3.Connection,
    run_id: str,
    lesson: MemoryRecord,
    use: LessonUse,
    at: str,
) -> LessonUpdate | None:
    if not _claim(
        connection,
        run_id,
        lesson.memory_id,
        "superseded",
        lesson.memory_id,
        "",
        at,
        use.correction_evidence,
    ):
        return None
    corrected = store.add_within(
        connection,
        kind=LESSON_KIND,
        subject=lesson.subject,
        content=use.correction,
        source_type="agent",
        source_ref=run_id,
        author=f"agent:{lesson.team}",
        team=lesson.team,
        created_at=at,
        valid_until=lesson.valid_until,
        confidence=0.5,
        supersedes=lesson.memory_id,
    )
    connection.execute(
        "UPDATE lesson_events SET result_id = ? WHERE run_id = ? AND lesson_key = ?",
        (corrected.memory_id, run_id, lesson.memory_id),
    )
    return LessonUpdate(
        run_id=run_id,
        lesson_id=lesson.memory_id,
        action="superseded",
        result_id=corrected.memory_id,
        evidence_refs=use.correction_evidence,
    )


def _retire(
    connection: sqlite3.Connection,
    run_id: str,
    lesson: MemoryRecord,
    use: LessonUse,
    at: str,
) -> LessonUpdate | None:
    if not _claim(
        connection,
        run_id,
        lesson.memory_id,
        "retired",
        lesson.memory_id,
        lesson.memory_id,
        at,
        use.evidence_refs,
    ):
        return None
    connection.execute(
        "UPDATE memories SET status = 'retired' WHERE memory_id = ?",
        (lesson.memory_id,),
    )
    return LessonUpdate(
        run_id=run_id,
        lesson_id=lesson.memory_id,
        action="retired",
        result_id=lesson.memory_id,
        evidence_refs=use.evidence_refs,
    )


def _settle_draft(
    store: MemoryStore,
    connection: sqlite3.Connection,
    run_id: str,
    draft: LessonDraft,
    at: str,
) -> LessonUpdate | None:
    digest = hashlib.sha256(
        f"{draft.role}|{draft.subject}|{draft.text}".encode()
    ).hexdigest()[:12]
    key = f"draft-{digest}"
    if not _claim(connection, run_id, key, "created", "", "", at, []):
        return None
    created = store.add_within(
        connection,
        kind=LESSON_KIND,
        subject=draft.subject,
        content=draft.text,
        source_type="agent",
        source_ref=run_id,
        author=f"agent:{draft.role}",
        team=draft.role,
        created_at=draft.created_at,
        valid_until=draft.valid_until,
        confidence=draft.confidence,
    )
    connection.execute(
        "UPDATE lesson_events SET memory_id = ?, result_id = ? WHERE run_id = ? AND lesson_key = ?",
        (created.memory_id, created.memory_id, run_id, key),
    )
    return LessonUpdate(
        run_id=run_id,
        lesson_id=created.memory_id,
        action="created",
        result_id=created.memory_id,
    )


def forget_lesson(
    store: MemoryStore, lesson_id: str, *, deleted_at: str, deleted_by: str, reason: str
) -> bool:
    """Delete a lesson's content through the store's deletion log; other kinds are left alone."""
    record = store.get(lesson_id)
    if record.kind != LESSON_KIND:
        raise ValueError(f"{lesson_id} is not a lesson")
    return store.delete(
        lesson_id, deleted_at=deleted_at, deleted_by=deleted_by, reason=reason
    )


# Snapshots ----------------------------------------------------------------------------------


def snapshot_memory(
    source: str | Path, destination: str | Path, *, frozen: bool = True
) -> str:
    """Copy a memory file with SQLite's backup API and return the content fingerprint.

    The source is opened read-only and never modified. With `frozen`, the copy refuses to learn.
    The fingerprint covers memories, deletions and settlements, so two copies of the same source
    have the same fingerprint whether or not they are frozen.
    """
    source_path, destination_path = Path(source), Path(destination)
    if destination_path.exists():
        raise FileExistsError(f"snapshot destination exists: {destination_path}")
    destination_path.parent.mkdir(parents=True, exist_ok=True)
    with (
        closing(sqlite3.connect(f"file:{source_path}?mode=ro", uri=True)) as origin,
        closing(sqlite3.connect(destination_path)) as copy,
    ):
        origin.backup(copy)
    with closing(sqlite3.connect(destination_path)) as copy, copy:
        for statement in _TABLES:
            copy.execute(statement)
        if frozen:
            copy.execute("INSERT INTO lesson_frozen VALUES (1)")
    return memory_fingerprint(destination_path)


def memory_fingerprint(path: str | Path) -> str:
    """Hash of memories, deletions and settlements; opens the file read-only."""
    digest = hashlib.sha256()
    with closing(sqlite3.connect(f"file:{Path(path)}?mode=ro", uri=True)) as connection:
        for query in _FINGERPRINT_QUERIES:
            try:
                rows = [list(row) for row in connection.execute(query).fetchall()]
            except sqlite3.OperationalError:
                rows = []
            digest.update(json.dumps(rows, sort_keys=True, default=str).encode())
    return digest.hexdigest()


def is_frozen(path: str | Path) -> bool:
    with closing(sqlite3.connect(Path(path))) as connection:
        exists = connection.execute(
            "SELECT 1 FROM sqlite_master WHERE name = 'lesson_frozen'"
        ).fetchone()
        if exists is None:
            return False
        return connection.execute("SELECT 1 FROM lesson_frozen").fetchone() is not None


# Team-facing functions ----------------------------------------------------------------------


class LessonSession:
    """One role's view of lessons during a run: what it read and which ids it cited.

    The harness wraps `read` and `cite` as tools. Only lessons returned by `read` can be cited, so
    a role cannot cite another role's lesson.
    """

    def __init__(self, store: MemoryStore, role: str, run_id: str) -> None:
        self.store = store
        self.role = role
        self.run_id = run_id
        self._retrieved: dict[str, Lesson] = {}
        self._uses: dict[str, LessonUse] = {}

    def read(self, subject: str, at: str) -> list[dict[str, Any]]:
        lessons = recall_lessons(self.store, self.role, subject, at)
        self._retrieved.update({lesson.lesson_id: lesson for lesson in lessons})
        return [
            {
                "lesson_id": lesson.lesson_id,
                "text": lesson.text,
                "confidence": lesson.confidence,
                "origin_run": lesson.origin_run,
            }
            for lesson in lessons
        ]

    def cite(
        self,
        lesson_ids: list[str],
        handoff_id: str = "",
        evidence_refs: list[str] | None = None,
    ) -> list[str]:
        """Record lessons the role used; returns the ids accepted (unread ids are ignored)."""
        accepted = [
            lesson_id for lesson_id in lesson_ids if lesson_id in self._retrieved
        ]
        for lesson_id in accepted:
            self._uses[lesson_id] = LessonUse(
                role=self.role,
                lesson_id=lesson_id,
                handoff_id=handoff_id,
                evidence_refs=evidence_refs or [],
            )
        return accepted

    def implicate(
        self,
        lesson_id: str,
        correction: str = "",
        correction_evidence: list[str] | None = None,
    ) -> bool:
        """Mark a cited lesson as behind a failing decision, optionally with a corrected text."""
        use = self._uses.get(lesson_id)
        if use is None:
            return False
        use.implicated = True
        use.correction = correction
        use.correction_evidence = correction_evidence or []
        return True

    def uses(self) -> list[LessonUse]:
        return list(self._uses.values())
