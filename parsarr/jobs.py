"""
Job store for Parsarr.

Jobs represent a single torrent/release moving through the Parsarr pipeline.
The store is backed by a local SQLite database (stdlib sqlite3).  All async
callers wrap the sync calls via run_in_executor to avoid blocking the event loop.
"""
from __future__ import annotations

import json
import logging
import sqlite3
import threading
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# State machine
# ---------------------------------------------------------------------------

class JobState(str, Enum):
    SUBMITTED = "submitted"
    METADATA_PENDING = "metadata_pending"
    METADATA_READY = "metadata_ready"
    AUTO_MAPPED = "auto_mapped"
    AWAITING_MANUAL_MAPPING = "awaiting_manual_mapping"
    DOWNLOADING = "downloading"
    REROUTED_TO_STAGING = "rerouted_to_staging"
    READY_TO_PROCESS = "ready_to_process"
    PROCESSING = "processing"
    PLACED = "placed"
    RESCAN_TRIGGERED = "rescan_triggered"
    COMPLETED = "completed"
    FAILED = "failed"
    # Standard release — no action taken, job exists for visibility only
    PASSTHROUGH = "passthrough"


# ---------------------------------------------------------------------------
# Job dataclass
# ---------------------------------------------------------------------------

class Job:
    __slots__ = (
        "id",
        "hash",
        "title",
        "sonarr_series_id",
        "state",
        "hold",
        "target_path",
        "file_tree_json",
        "mapping_json",
        "placement_mode",
        "error",
        "created_at",
        "updated_at",
    )

    def __init__(
        self,
        id: int,
        hash: str,
        title: str,
        sonarr_series_id: Optional[int],
        state: str,
        hold: bool,
        target_path: Optional[str],
        file_tree_json: Optional[str],
        mapping_json: Optional[str],
        placement_mode: str,
        error: Optional[str],
        created_at: str,
        updated_at: str,
    ) -> None:
        self.id = id
        self.hash = hash
        self.title = title
        self.sonarr_series_id = sonarr_series_id
        self.state = state
        self.hold = hold
        self.target_path = target_path
        self.file_tree_json = file_tree_json
        self.mapping_json = mapping_json
        self.placement_mode = placement_mode
        self.error = error
        self.created_at = created_at
        self.updated_at = updated_at

    def as_dict(self) -> dict:
        return {s: getattr(self, s) for s in self.__slots__}

    @property
    def mapping(self) -> Optional[dict]:
        if self.mapping_json:
            return json.loads(self.mapping_json)
        return None

    @property
    def file_tree(self) -> Optional[list]:
        if self.file_tree_json:
            return json.loads(self.file_tree_json)
        return None


# ---------------------------------------------------------------------------
# Database helper
# ---------------------------------------------------------------------------

_DDL = """
CREATE TABLE IF NOT EXISTS jobs (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    hash            TEXT NOT NULL,
    title           TEXT NOT NULL,
    sonarr_series_id INTEGER,
    state           TEXT NOT NULL DEFAULT 'submitted',
    hold            INTEGER NOT NULL DEFAULT 0,
    target_path     TEXT,
    file_tree_json  TEXT,
    mapping_json    TEXT,
    placement_mode  TEXT NOT NULL DEFAULT 'move',
    error           TEXT,
    created_at      TEXT NOT NULL,
    updated_at      TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS jobs_hash_idx ON jobs(hash);
CREATE INDEX IF NOT EXISTS jobs_state_idx ON jobs(state);
"""


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _row_to_job(row: tuple) -> Job:
    return Job(
        id=row[0],
        hash=row[1],
        title=row[2],
        sonarr_series_id=row[3],
        state=row[4],
        hold=bool(row[5]),
        target_path=row[6],
        file_tree_json=row[7],
        mapping_json=row[8],
        placement_mode=row[9],
        error=row[10],
        created_at=row[11],
        updated_at=row[12],
    )


class JobStore:
    """Thread-safe SQLite-backed job store."""

    def __init__(self, db_path: Path) -> None:
        self._db_path = db_path
        self._lock = threading.Lock()
        db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(str(self._db_path), check_same_thread=False)
        conn.row_factory = sqlite3.Row
        return conn

    def _init_db(self) -> None:
        with self._lock, self._connect() as conn:
            conn.executescript(_DDL)

    # ------------------------------------------------------------------
    # Write operations
    # ------------------------------------------------------------------

    def create_job(
        self,
        hash: str,
        title: str,
        sonarr_series_id: Optional[int] = None,
        placement_mode: str = "move",
        state: str = JobState.SUBMITTED,
    ) -> Job:
        now = _now()
        with self._lock, self._connect() as conn:
            cur = conn.execute(
                """
                INSERT INTO jobs (hash, title, sonarr_series_id, state,
                                  placement_mode, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (hash, title, sonarr_series_id, state, placement_mode, now, now),
            )
            return self.get_job(cur.lastrowid)  # type: ignore[arg-type]

    def update_job_state(
        self,
        job_id: int,
        state: str,
        error: Optional[str] = None,
    ) -> Optional[Job]:
        now = _now()
        with self._lock, self._connect() as conn:
            conn.execute(
                "UPDATE jobs SET state=?, error=?, updated_at=? WHERE id=?",
                (state, error, now, job_id),
            )
        return self.get_job(job_id)

    def update_job_mapping(
        self,
        job_id: int,
        mapping: dict,
        target_path: Optional[str] = None,
    ) -> Optional[Job]:
        now = _now()
        with self._lock, self._connect() as conn:
            conn.execute(
                """
                UPDATE jobs
                SET mapping_json=?, target_path=?, updated_at=?
                WHERE id=?
                """,
                (json.dumps(mapping), target_path, now, job_id),
            )
        return self.get_job(job_id)

    def update_file_tree(self, job_id: int, file_tree: list) -> Optional[Job]:
        now = _now()
        with self._lock, self._connect() as conn:
            conn.execute(
                "UPDATE jobs SET file_tree_json=?, updated_at=? WHERE id=?",
                (json.dumps(file_tree), now, job_id),
            )
        return self.get_job(job_id)

    def set_hold(self, job_id: int, hold: bool) -> Optional[Job]:
        now = _now()
        with self._lock, self._connect() as conn:
            conn.execute(
                "UPDATE jobs SET hold=?, updated_at=? WHERE id=?",
                (int(hold), now, job_id),
            )
        return self.get_job(job_id)

    def set_target_path(self, job_id: int, target_path: str) -> Optional[Job]:
        now = _now()
        with self._lock, self._connect() as conn:
            conn.execute(
                "UPDATE jobs SET target_path=?, updated_at=? WHERE id=?",
                (target_path, now, job_id),
            )
        return self.get_job(job_id)

    # ------------------------------------------------------------------
    # Read operations
    # ------------------------------------------------------------------

    def get_job(self, job_id: int) -> Optional[Job]:
        with self._lock, self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM jobs WHERE id=?", (job_id,)
            ).fetchone()
            return _row_to_job(tuple(row)) if row else None

    def get_job_by_hash(self, hash: str) -> Optional[Job]:
        with self._lock, self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM jobs WHERE hash=? ORDER BY id DESC LIMIT 1",
                (hash,),
            ).fetchone()
            return _row_to_job(tuple(row)) if row else None

    def list_jobs(self, limit: int = 200, offset: int = 0) -> list[Job]:
        with self._lock, self._connect() as conn:
            rows = conn.execute(
                "SELECT * FROM jobs ORDER BY id DESC LIMIT ? OFFSET ?",
                (limit, offset),
            ).fetchall()
            return [_row_to_job(tuple(r)) for r in rows]
