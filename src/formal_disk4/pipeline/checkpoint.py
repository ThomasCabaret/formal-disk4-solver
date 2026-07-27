from __future__ import annotations

import hashlib
import json
import sqlite3
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Mapping


CHECKPOINT_SCHEMA_VERSION = 1
SEARCH_SEMANTICS_VERSION = "formal-contour-search-v6"


def _utc_now_text() -> str:
    return datetime.now(timezone.utc).isoformat()


def search_fingerprint(config: Mapping[str, Any]) -> str:
    """Hash only options that change which mathematical cases are processed.

    Runtime limits, progress formatting, output paths and checkpoint cadence are
    deliberately excluded so a stopped run can be resumed with a different time
    budget or display interval.
    """

    payload = {
        "search_semantics_version": SEARCH_SEMANTICS_VERSION,
        "maps": config.get("maps"),
        "enumeration": config.get("enumeration"),
        "solver": config.get("solver"),
        "filters": config.get("filters"),
    }
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class LoadedCheckpoint:
    resumed: bool
    completed: bool
    state: Dict[str, Any]
    stats: Dict[str, Any]
    updated_utc: str | None


class CheckpointStore:
    """Compact SQLite checkpoint plus an authoritative survivor table.

    The checkpoint table contains one JSON search cursor and cumulative counters.
    It does not store visited nodes, rejected placements, word systems or solver
    states. The survivors table stores only profiles that passed the pipeline.
    """

    def __init__(
        self,
        path: Path,
        *,
        fingerprint: str,
        interval_seconds: float = 60.0,
        enabled: bool = True,
        resume: bool = True,
        restart: bool = False,
    ) -> None:
        self.path = path
        self.fingerprint = fingerprint
        self.interval_seconds = max(1.0, float(interval_seconds))
        self.enabled = bool(enabled)
        self.resume = bool(resume)
        self.restart = bool(restart)
        self._last_saved = 0.0
        self.connection: sqlite3.Connection | None = None

        if not self.enabled:
            return
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.connection = sqlite3.connect(str(self.path), timeout=30.0)
        self.connection.execute("PRAGMA journal_mode=WAL")
        self.connection.execute("PRAGMA synchronous=NORMAL")
        self.connection.executescript(
            """
            CREATE TABLE IF NOT EXISTS search_checkpoint (
                singleton INTEGER PRIMARY KEY CHECK (singleton = 1),
                schema_version INTEGER NOT NULL,
                config_fingerprint TEXT NOT NULL,
                updated_utc TEXT NOT NULL,
                completed INTEGER NOT NULL,
                state_json TEXT NOT NULL,
                stats_json TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS survivors (
                profile_key TEXT PRIMARY KEY,
                created_utc TEXT NOT NULL,
                payload_json TEXT NOT NULL
            );
            """
        )
        self.connection.commit()
        if self.restart:
            self.reset()

    def close(self) -> None:
        if self.connection is not None:
            self.connection.commit()
            self.connection.close()
            self.connection = None

    def __del__(self) -> None:
        try:
            self.close()
        except Exception:
            pass

    def reset(self) -> None:
        if self.connection is None:
            return
        self.connection.execute("DELETE FROM search_checkpoint")
        self.connection.execute("DELETE FROM survivors")
        self.connection.commit()

    def load(self) -> LoadedCheckpoint:
        if self.connection is None or not self.resume:
            return LoadedCheckpoint(False, False, {}, {}, None)
        row = self.connection.execute(
            "SELECT schema_version, config_fingerprint, updated_utc, completed, "
            "state_json, stats_json FROM search_checkpoint WHERE singleton = 1"
        ).fetchone()
        if row is None:
            return LoadedCheckpoint(False, False, {}, {}, None)
        schema_version, fingerprint, updated_utc, completed, state_json, stats_json = row
        if int(schema_version) != CHECKPOINT_SCHEMA_VERSION:
            raise RuntimeError(
                f"Checkpoint schema {schema_version} is incompatible with expected "
                f"schema {CHECKPOINT_SCHEMA_VERSION}. Use --restart or another output directory."
            )
        if str(fingerprint) != self.fingerprint:
            raise RuntimeError(
                "Existing checkpoint was created with different search semantics. "
                "Use --restart to discard it, or choose another output directory."
            )
        return LoadedCheckpoint(
            resumed=True,
            completed=bool(completed),
            state=json.loads(state_json),
            stats=json.loads(stats_json),
            updated_utc=str(updated_utc),
        )

    def save(
        self,
        state: Mapping[str, Any],
        stats: Mapping[str, Any],
        *,
        completed: bool = False,
        force: bool = False,
    ) -> bool:
        if self.connection is None:
            return False
        now = time.monotonic()
        if not force and now - self._last_saved < self.interval_seconds:
            return False
        self.connection.execute(
            """
            INSERT INTO search_checkpoint(
                singleton, schema_version, config_fingerprint, updated_utc,
                completed, state_json, stats_json
            ) VALUES(1, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(singleton) DO UPDATE SET
                schema_version=excluded.schema_version,
                config_fingerprint=excluded.config_fingerprint,
                updated_utc=excluded.updated_utc,
                completed=excluded.completed,
                state_json=excluded.state_json,
                stats_json=excluded.stats_json
            """,
            (
                CHECKPOINT_SCHEMA_VERSION,
                self.fingerprint,
                _utc_now_text(),
                1 if completed else 0,
                json.dumps(state, sort_keys=True, separators=(",", ":")),
                json.dumps(stats, sort_keys=True, separators=(",", ":")),
            ),
        )
        self.connection.commit()
        self._last_saved = now
        return True

    def store_survivor(self, profile_key: str, payload: Mapping[str, Any]) -> bool:
        """Insert a survivor exactly once and commit before JSONL export."""

        if self.connection is None:
            return True
        serialized = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
        cursor = self.connection.execute(
            "INSERT OR IGNORE INTO survivors(profile_key, created_utc, payload_json) "
            "VALUES(?, ?, ?)",
            (profile_key, _utc_now_text(), serialized),
        )
        self.connection.commit()
        return cursor.rowcount == 1


    def import_survivors_jsonl(self, path: Path) -> int:
        """Import an existing survivor JSONL when adopting a pre-checkpoint output directory."""

        if self.connection is None or not path.exists():
            return 0
        imported = 0
        with path.open("r", encoding="utf-8") as handle:
            for line_number, line in enumerate(handle, 1):
                text = line.strip()
                if not text:
                    continue
                try:
                    payload = json.loads(text)
                except json.JSONDecodeError as error:
                    raise RuntimeError(
                        f"Cannot import existing survivor file {path} at line {line_number}: {error}"
                    ) from error
                normalized = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
                legacy_key = "legacy:" + hashlib.sha256(normalized.encode("utf-8")).hexdigest()
                cursor = self.connection.execute(
                    "INSERT OR IGNORE INTO survivors(profile_key, created_utc, payload_json) "
                    "VALUES(?, ?, ?)",
                    (legacy_key, _utc_now_text(), json.dumps(payload, ensure_ascii=False, separators=(",", ":"))),
                )
                imported += 1 if cursor.rowcount == 1 else 0
        self.connection.commit()
        return imported

    def export_survivors_jsonl(self, path: Path) -> int:
        """Rebuild the human-readable survivor file from the SQLite source of truth."""

        if self.connection is None:
            return 0
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_suffix(path.suffix + ".tmp")
        count = 0
        with temporary.open("w", encoding="utf-8") as handle:
            for (payload_json,) in self.connection.execute(
                "SELECT payload_json FROM survivors ORDER BY rowid"
            ):
                handle.write(str(payload_json))
                handle.write("\n")
                count += 1
        temporary.replace(path)
        return count

    def survivor_count(self) -> int:
        if self.connection is None:
            return 0
        row = self.connection.execute("SELECT COUNT(*) FROM survivors").fetchone()
        return int(row[0]) if row else 0
