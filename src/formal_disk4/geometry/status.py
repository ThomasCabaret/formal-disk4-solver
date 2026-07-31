from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable


GEOMETRY_STATUS_SCHEMA_VERSION = 1
SOLUTION_FOUND = "solution_found"
REJECTED_CERTAIN = "rejected_certain"
NO_SOLUTION_FOUND = "no_solution_found"
GEOMETRY_STATUSES = (SOLUTION_FOUND, REJECTED_CERTAIN, NO_SOLUTION_FOUND)


def _utc_now_text() -> str:
    return datetime.now(timezone.utc).isoformat()


def remove_sqlite_files(path: Path) -> None:
    """Remove a SQLite database and its transient sidecars if they exist."""

    for suffix in ("", "-wal", "-shm"):
        candidate = Path(str(path) + suffix)
        try:
            candidate.unlink()
        except FileNotFoundError:
            pass


@dataclass(frozen=True)
class GeometryStatusCounts:
    solution_found: int = 0
    rejected_certain: int = 0
    no_solution_found: int = 0

    @property
    def considered(self) -> int:
        return self.solution_found + self.rejected_certain + self.no_solution_found


@dataclass(frozen=True)
class GeometryStatusSnapshot:
    counts: GeometryStatusCounts
    history_complete: bool


class GeometryStatusStore:
    """Persistent latest status for each formal candidate tested by geometry.

    The geometry checkpoint intentionally records cumulative attempts because
    unresolved candidates are retried on later passes. This store instead keeps
    one current classification per formal profile so the GUI can display exact
    candidate counts without counting retries twice.
    """

    def __init__(self, path: Path, *, history_complete: bool = True) -> None:
        self.path = path
        self.path.parent.mkdir(parents=True, exist_ok=True)
        database_existed = self.path.exists()
        self.connection = sqlite3.connect(str(path), timeout=30.0)
        self.connection.execute("PRAGMA journal_mode=WAL")
        self.connection.execute("PRAGMA synchronous=NORMAL")
        self.connection.executescript(
            """
            CREATE TABLE IF NOT EXISTS geometry_status_meta (
                singleton INTEGER PRIMARY KEY CHECK (singleton = 1),
                schema_version INTEGER NOT NULL,
                history_complete INTEGER NOT NULL
            );
            CREATE TABLE IF NOT EXISTS geometry_candidate_status (
                formal_profile_id TEXT PRIMARY KEY,
                status TEXT NOT NULL,
                reason TEXT NOT NULL,
                attempts INTEGER NOT NULL,
                best_cost REAL,
                updated_utc TEXT NOT NULL
            );
            """
        )
        row = self.connection.execute(
            "SELECT schema_version, history_complete FROM geometry_status_meta "
            "WHERE singleton = 1"
        ).fetchone()
        if row is None:
            self.connection.execute(
                "INSERT INTO geometry_status_meta(" 
                "singleton, schema_version, history_complete) VALUES(1, ?, ?)",
                (GEOMETRY_STATUS_SCHEMA_VERSION, 1 if history_complete else 0),
            )
        elif int(row[0]) != GEOMETRY_STATUS_SCHEMA_VERSION:
            self.connection.close()
            raise RuntimeError(
                "Geometry status database is incompatible. Use --restart to recreate it."
            )
        elif not database_existed:
            self.set_history_complete(history_complete)
        self.connection.commit()

    def close(self) -> None:
        if self.connection is not None:
            self.connection.commit()
            self.connection.close()
            self.connection = None  # type: ignore[assignment]

    def __enter__(self) -> "GeometryStatusStore":
        return self

    def __exit__(self, _exc_type, _exc, _traceback) -> None:
        self.close()

    def set_history_complete(self, complete: bool) -> None:
        self.connection.execute(
            "UPDATE geometry_status_meta SET history_complete = ? WHERE singleton = 1",
            (1 if complete else 0,),
        )
        self.connection.commit()

    def record(
        self,
        formal_profile_id: str,
        status: str,
        *,
        reason: str,
        attempts: int,
        best_cost: float | None,
    ) -> None:
        if status not in GEOMETRY_STATUSES:
            raise ValueError(f"Unsupported geometry status: {status}")
        self.connection.execute(
            """
            INSERT INTO geometry_candidate_status(
                formal_profile_id, status, reason, attempts, best_cost, updated_utc
            ) VALUES(?, ?, ?, ?, ?, ?)
            ON CONFLICT(formal_profile_id) DO UPDATE SET
                status=excluded.status,
                reason=excluded.reason,
                attempts=excluded.attempts,
                best_cost=excluded.best_cost,
                updated_utc=excluded.updated_utc
            """,
            (
                formal_profile_id,
                status,
                reason,
                int(attempts),
                best_cost,
                _utc_now_text(),
            ),
        )
        self.connection.commit()

    def record_existing_solutions(self, formal_profile_ids: Iterable[str]) -> None:
        now = _utc_now_text()
        self.connection.executemany(
            """
            INSERT INTO geometry_candidate_status(
                formal_profile_id, status, reason, attempts, best_cost, updated_utc
            ) VALUES(?, ?, ?, 0, NULL, ?)
            ON CONFLICT(formal_profile_id) DO UPDATE SET
                status=excluded.status,
                reason=excluded.reason,
                updated_utc=excluded.updated_utc
            """,
            (
                (profile_id, SOLUTION_FOUND, "persisted geometric solution", now)
                for profile_id in formal_profile_ids
            ),
        )
        self.connection.commit()

    def counts(self) -> GeometryStatusCounts:
        values = {status: 0 for status in GEOMETRY_STATUSES}
        for status, count in self.connection.execute(
            "SELECT status, COUNT(*) FROM geometry_candidate_status GROUP BY status"
        ):
            if str(status) in values:
                values[str(status)] = int(count)
        return GeometryStatusCounts(
            solution_found=values[SOLUTION_FOUND],
            rejected_certain=values[REJECTED_CERTAIN],
            no_solution_found=values[NO_SOLUTION_FOUND],
        )


def read_geometry_status(path: Path) -> GeometryStatusSnapshot | None:
    if not path.exists():
        return None
    try:
        connection = sqlite3.connect(str(path), timeout=1.0)
        try:
            row = connection.execute(
                "SELECT schema_version, history_complete FROM geometry_status_meta "
                "WHERE singleton = 1"
            ).fetchone()
            if row is None or int(row[0]) != GEOMETRY_STATUS_SCHEMA_VERSION:
                return None
            values = {status: 0 for status in GEOMETRY_STATUSES}
            for status, count in connection.execute(
                "SELECT status, COUNT(*) FROM geometry_candidate_status GROUP BY status"
            ):
                if str(status) in values:
                    values[str(status)] = int(count)
        finally:
            connection.close()
    except (sqlite3.Error, OSError, ValueError):
        return None
    return GeometryStatusSnapshot(
        counts=GeometryStatusCounts(
            solution_found=values[SOLUTION_FOUND],
            rejected_certain=values[REJECTED_CERTAIN],
            no_solution_found=values[NO_SOLUTION_FOUND],
        ),
        history_complete=bool(row[1]),
    )


def read_geometry_status_counts(path: Path) -> GeometryStatusCounts | None:
    snapshot = read_geometry_status(path)
    return None if snapshot is None else snapshot.counts
