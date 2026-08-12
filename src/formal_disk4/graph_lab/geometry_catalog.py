from __future__ import annotations

import json
import sqlite3
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping

from formal_disk4.geometry.status import GeometryCandidateStatus


CATALOG_SCHEMA_VERSION = 2


@dataclass(frozen=True)
class CatalogCandidate:
    formal_profile_id: str
    source_offset: int
    source_length: int


class GeometryCandidateCatalog:
    """Compact persistent index over the potentially multi-gigabyte JSONL queue."""

    def __init__(self, path: Path, source: Path) -> None:
        self.path = path.resolve()
        self.source = source.resolve()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.lock = threading.RLock()
        self.connection = sqlite3.connect(
            str(self.path), timeout=30.0, check_same_thread=False
        )
        self.connection.execute("PRAGMA journal_mode=WAL")
        self.connection.execute("PRAGMA synchronous=NORMAL")
        self.connection.executescript(
            """
            CREATE TABLE IF NOT EXISTS catalog_meta (
                singleton INTEGER PRIMARY KEY CHECK(singleton = 1),
                schema_version INTEGER NOT NULL,
                source_path TEXT NOT NULL,
                source_offset INTEGER NOT NULL,
                source_line INTEGER NOT NULL,
                malformed_lines INTEGER NOT NULL
            );
            CREATE TABLE IF NOT EXISTS geometry_candidate_catalog (
                formal_profile_id TEXT PRIMARY KEY,
                source_offset INTEGER NOT NULL,
                source_length INTEGER NOT NULL,
                first_line INTEGER NOT NULL,
                last_line INTEGER NOT NULL,
                occurrences INTEGER NOT NULL,
                generation INTEGER,
                graph_id TEXT,
                map_name TEXT,
                tile_count INTEGER,
                edge_count INTEGER,
                symmetry_order INTEGER,
                is_pizza INTEGER NOT NULL,
                pizza_kind TEXT NOT NULL DEFAULT 'non_ring'
            );
            CREATE INDEX IF NOT EXISTS geometry_candidate_catalog_last_line
            ON geometry_candidate_catalog(last_line DESC);
            """
        )
        catalog_columns = {
            str(row[1])
            for row in self.connection.execute(
                "PRAGMA table_info(geometry_candidate_catalog)"
            )
        }
        migrated_classification = False
        if "pizza_kind" not in catalog_columns:
            self.connection.execute(
                "ALTER TABLE geometry_candidate_catalog "
                "ADD COLUMN pizza_kind TEXT NOT NULL DEFAULT 'non_ring'"
            )
            migrated_classification = True
        row = self.connection.execute(
            "SELECT schema_version, source_path FROM catalog_meta WHERE singleton=1"
        ).fetchone()
        if row is None:
            self._write_meta(0, 0, 0)
        elif int(row[0]) not in (1, CATALOG_SCHEMA_VERSION):
            self.connection.close()
            raise RuntimeError("Geometry candidate catalog is incompatible")
        else:
            if int(row[0]) == 1:
                migrated_classification = True
                self.connection.execute(
                    "UPDATE catalog_meta SET schema_version=? WHERE singleton=1",
                    (CATALOG_SCHEMA_VERSION,),
                )
            if str(row[1]) != str(self.source):
                self.reset()
                migrated_classification = False
        self.connection.commit()
        if migrated_classification:
            self._reclassify_existing()

    def close(self) -> None:
        with self.lock:
            if self.connection is not None:
                self.connection.commit()
                self.connection.close()
                self.connection = None  # type: ignore[assignment]

    def _write_meta(self, offset: int, line: int, malformed: int) -> None:
        self.connection.execute(
            """
            INSERT INTO catalog_meta(
                singleton, schema_version, source_path, source_offset,
                source_line, malformed_lines
            ) VALUES(1, ?, ?, ?, ?, ?)
            ON CONFLICT(singleton) DO UPDATE SET
                schema_version=excluded.schema_version,
                source_path=excluded.source_path,
                source_offset=excluded.source_offset,
                source_line=excluded.source_line,
                malformed_lines=excluded.malformed_lines
            """,
            (
                CATALOG_SCHEMA_VERSION,
                str(self.source),
                int(offset),
                int(line),
                int(malformed),
            ),
        )

    def reset(self) -> None:
        with self.lock:
            self.connection.execute("DELETE FROM geometry_candidate_catalog")
            self._write_meta(0, 0, 0)
            self.connection.commit()

    def progress(self) -> dict[str, int]:
        with self.lock:
            row = self.connection.execute(
                "SELECT source_offset, source_line, malformed_lines FROM catalog_meta "
                "WHERE singleton=1"
            ).fetchone()
            count = self.connection.execute(
                "SELECT COUNT(*) FROM geometry_candidate_catalog"
            ).fetchone()[0]
        return {
            "source_offset": int(row[0]) if row else 0,
            "source_line": int(row[1]) if row else 0,
            "malformed_lines": int(row[2]) if row else 0,
            "unique_candidates": int(count),
        }

    @staticmethod
    def _pizza_kind(
        tile_count: int,
        raw_edges: object,
        assignment: object,
    ) -> str:
        """Return a conservative ring classification.

        A pizza must be exactly a simple cycle of all tiles plus one outside
        edge incident to every tile. Imposed symmetry is deliberately ignored:
        it is a search restriction, not the symmetry realized by a solution.
        """

        if tile_count < 3 or not isinstance(raw_edges, list):
            return "non_ring"
        edges: set[tuple[int, int]] = set()
        for raw_edge in raw_edges:
            if not isinstance(raw_edge, (list, tuple)) or len(raw_edge) != 2:
                return "non_ring"
            try:
                left, right = int(raw_edge[0]), int(raw_edge[1])
            except (TypeError, ValueError):
                return "non_ring"
            if left == right:
                return "non_ring"
            edge = (left, right) if left < right else (right, left)
            edges.add(edge)
        # Reject duplicate/multi-edge encodings instead of risking a false
        # pizza label on a malformed or richer contact graph.
        if len(edges) != len(raw_edges) or len(edges) != 2 * tile_count:
            return "non_ring"
        expected_tiles = set(range(tile_count))
        outside_edges = {(-1, tile) for tile in expected_tiles}
        if not outside_edges.issubset(edges):
            return "non_ring"
        internal = edges - outside_edges
        if len(internal) != tile_count:
            return "non_ring"
        adjacency = {tile: set() for tile in expected_tiles}
        for left, right in internal:
            if left not in expected_tiles or right not in expected_tiles:
                return "non_ring"
            adjacency[left].add(right)
            adjacency[right].add(left)
        if any(len(neighbours) != 2 for neighbours in adjacency.values()):
            return "non_ring"
        seen = {0}
        pending = [0]
        while pending:
            for neighbour in adjacency[pending.pop()]:
                if neighbour not in seen:
                    seen.add(neighbour)
                    pending.append(neighbour)
        if seen != expected_tiles:
            return "non_ring"

        signs: set[int] = set()
        if isinstance(assignment, Mapping):
            raw_signs = assignment.get("orientation_signs")
            if isinstance(raw_signs, Mapping) and len(raw_signs) == tile_count:
                try:
                    signs = {1 if int(value) > 0 else -1 for value in raw_signs.values()}
                except (TypeError, ValueError):
                    signs = set()
        if len(signs) == 1:
            return "uniform_orientation_ring"
        if len(signs) > 1:
            return "mixed_orientation_ring"
        return "ring"

    @classmethod
    def _metadata(cls, record: Mapping[str, Any]) -> dict[str, object]:
        graph_lab = record.get("graph_lab", {})
        graph_lab = graph_lab if isinstance(graph_lab, Mapping) else {}
        candidate = graph_lab.get("structural_candidate", {})
        candidate = candidate if isinstance(candidate, Mapping) else {}
        raw_map = record.get("map", {})
        map_name = (
            str(raw_map.get("name", ""))
            if isinstance(raw_map, Mapping)
            else str(raw_map or "")
        )
        tile_count = int(candidate.get("tile_count", 0) or 0)
        raw_edges = candidate.get("edges", ())
        edge_count = len(raw_edges) if isinstance(raw_edges, list) else 0
        symmetry_order = int(candidate.get("symmetry_order", 1) or 1)
        pizza_kind = cls._pizza_kind(
            tile_count, raw_edges, record.get("assignment")
        )
        is_pizza = pizza_kind != "non_ring"
        return {
            "generation": (
                int(graph_lab["generation"])
                if graph_lab.get("generation") is not None
                else None
            ),
            "graph_id": str(graph_lab.get("graph_id", "")),
            "map_name": map_name,
            "tile_count": tile_count,
            "edge_count": edge_count,
            "symmetry_order": symmetry_order,
            "is_pizza": 1 if is_pizza else 0,
            "pizza_kind": pizza_kind,
        }

    def _reclassify_existing(self) -> None:
        """Upgrade the small persistent index without rescanning the JSONL."""

        with self.lock:
            rows = self.connection.execute(
                "SELECT formal_profile_id, source_offset, source_length "
                "FROM geometry_candidate_catalog"
            ).fetchall()
            if not self.source.exists():
                return
            with self.source.open("rb") as stream:
                for profile_id, offset, length in rows:
                    stream.seek(int(offset))
                    try:
                        record = json.loads(stream.read(int(length)).decode("utf-8"))
                    except (UnicodeDecodeError, json.JSONDecodeError):
                        continue
                    if not isinstance(record, Mapping):
                        continue
                    metadata = self._metadata(record)
                    self.connection.execute(
                        "UPDATE geometry_candidate_catalog "
                        "SET is_pizza=?, pizza_kind=? WHERE formal_profile_id=?",
                        (
                            metadata["is_pizza"],
                            metadata["pizza_kind"],
                            str(profile_id),
                        ),
                    )
            self.connection.commit()

    def ingest(self, *, maximum_lines: int | None = None) -> dict[str, int]:
        """Index all currently complete appended lines and return the progress."""

        with self.lock:
            if not self.source.exists():
                return self.progress()
            row = self.connection.execute(
                "SELECT source_offset, source_line, malformed_lines FROM catalog_meta "
                "WHERE singleton=1"
            ).fetchone()
            offset, line_number, malformed = (
                (int(row[0]), int(row[1]), int(row[2])) if row else (0, 0, 0)
            )
            if self.source.stat().st_size < offset:
                self.reset()
                offset = line_number = malformed = 0
            processed = 0
            with self.source.open("rb") as stream:
                stream.seek(offset)
                while maximum_lines is None or processed < maximum_lines:
                    line_offset = stream.tell()
                    raw = stream.readline()
                    if not raw:
                        break
                    if not raw.endswith(b"\n"):
                        stream.seek(line_offset)
                        break
                    offset = stream.tell()
                    line_number += 1
                    processed += 1
                    if not raw.strip():
                        continue
                    try:
                        record = json.loads(raw.decode("utf-8"))
                    except (UnicodeDecodeError, json.JSONDecodeError):
                        malformed += 1
                        continue
                    if not isinstance(record, Mapping):
                        malformed += 1
                        continue
                    profile_id = record.get("formal_profile_id")
                    if not isinstance(profile_id, str) or not profile_id:
                        malformed += 1
                        continue
                    metadata = self._metadata(record)
                    self.connection.execute(
                        """
                        INSERT INTO geometry_candidate_catalog(
                            formal_profile_id, source_offset, source_length,
                            first_line, last_line, occurrences, generation,
                            graph_id, map_name, tile_count, edge_count,
                            symmetry_order, is_pizza, pizza_kind
                        ) VALUES(?, ?, ?, ?, ?, 1, ?, ?, ?, ?, ?, ?, ?, ?)
                        ON CONFLICT(formal_profile_id) DO UPDATE SET
                            last_line=excluded.last_line,
                            occurrences=geometry_candidate_catalog.occurrences + 1,
                            generation=COALESCE(excluded.generation,
                                geometry_candidate_catalog.generation),
                            is_pizza=excluded.is_pizza,
                            pizza_kind=excluded.pizza_kind
                        """,
                        (
                            profile_id,
                            line_offset,
                            len(raw),
                            line_number,
                            line_number,
                            metadata["generation"],
                            metadata["graph_id"],
                            metadata["map_name"],
                            metadata["tile_count"],
                            metadata["edge_count"],
                            metadata["symmetry_order"],
                            metadata["is_pizza"],
                            metadata["pizza_kind"],
                        ),
                    )
                    if processed % 250 == 0:
                        self._write_meta(offset, line_number, malformed)
                        self.connection.commit()
            self._write_meta(offset, line_number, malformed)
            self.connection.commit()
            return self.progress()

    def pending(
        self, considered_ids: set[str], *, limit: int
    ) -> list[CatalogCandidate]:
        with self.lock:
            rows = self.connection.execute(
                "SELECT formal_profile_id, source_offset, source_length "
                "FROM geometry_candidate_catalog ORDER BY first_line ASC"
            )
            output = []
            for profile_id, offset, length in rows:
                if str(profile_id) in considered_ids:
                    continue
                output.append(
                    CatalogCandidate(str(profile_id), int(offset), int(length))
                )
                if len(output) >= max(1, int(limit)):
                    break
            return output

    def read_raw(self, candidate: CatalogCandidate) -> bytes:
        with self.source.open("rb") as stream:
            stream.seek(candidate.source_offset)
            return stream.read(candidate.source_length)

    def page(
        self,
        *,
        page: int,
        page_size: int,
        statuses: Mapping[str, GeometryCandidateStatus],
        processing_profile_id: str | None,
        include_importance: set[str] | None = None,
        include_statuses: set[str] | None = None,
    ) -> dict[str, object]:
        size = min(100, max(1, int(page_size)))
        requested_page = max(1, int(page))
        with self.lock:
            rows = self.connection.execute(
                """
                SELECT formal_profile_id, first_line, last_line, occurrences,
                       generation, graph_id, map_name, tile_count, edge_count,
                       symmetry_order, is_pizza, pizza_kind
                FROM geometry_candidate_catalog
                ORDER BY last_line DESC
                """
            ).fetchall()
        all_items = []
        for row in rows:
            profile_id = str(row[0])
            status = statuses.get(profile_id)
            status_name = (
                "processing"
                if profile_id == processing_profile_id
                else (status.status if status is not None else "pending")
            )
            tile_count = int(row[7] or 0)
            is_pizza = bool(row[10])
            importance = (
                "pizza"
                if is_pizza
                else ("alert" if tile_count and tile_count < 12 else "important")
            )
            all_items.append(
                {
                    "formal_profile_id": profile_id,
                    "first_line": int(row[1]),
                    "last_line": int(row[2]),
                    "occurrences": int(row[3]),
                    "generation": row[4],
                    "graph_id": row[5],
                    "map_name": row[6],
                    "tile_count": tile_count,
                    "edge_count": int(row[8] or 0),
                    "symmetry_order": int(row[9] or 1),
                    "is_pizza": is_pizza,
                    "pizza_kind": str(
                        (row[11] or "ring") if is_pizza else "non_ring"
                    ),
                    "importance": importance,
                    "status": status_name,
                    "reason": status.reason if status is not None else None,
                    "attempts": status.attempts if status is not None else None,
                    "best_cost": status.best_cost if status is not None else None,
                    "updated_utc": status.updated_utc if status is not None else None,
                    "preview_url": (
                        f"/api/solution-svg?profile={profile_id}"
                        if status_name == "solution_found"
                        else None
                    ),
                }
            )
        allowed_importance = (
            {"pizza", "important", "alert"}
            if include_importance is None
            else include_importance
        )
        allowed_statuses = (
            {
                "pending",
                "processing",
                "solution_found",
                "rejected_certain",
                "no_solution_found",
            }
            if include_statuses is None
            else include_statuses
        )
        filtered = [
            item
            for item in all_items
            if item["importance"] in allowed_importance
            and item["status"] in allowed_statuses
        ]
        total = len(filtered)
        pages = max(1, (total + size - 1) // size)
        current_page = min(requested_page, pages)
        offset = (current_page - 1) * size
        items = filtered[offset : offset + size]
        catalog_ids = {str(item["formal_profile_id"]) for item in all_items}
        counts = {
            "pending": sum(item["status"] == "pending" for item in all_items),
            "processing": sum(item["status"] == "processing" for item in all_items),
            "solution_found": sum(
                value.status == "solution_found"
                for key, value in statuses.items()
                if key in catalog_ids
            ),
            "rejected_certain": sum(
                value.status == "rejected_certain"
                for key, value in statuses.items()
                if key in catalog_ids
            ),
            "no_solution_found": sum(
                value.status == "no_solution_found"
                for key, value in statuses.items()
                if key in catalog_ids
            ),
        }
        return {
            "page": current_page,
            "page_size": size,
            "pages": pages,
            "total": total,
            "distinct_total": len(all_items),
            "occurrences_total": sum(int(item["occurrences"]) for item in all_items),
            "counts": counts,
            "items": items,
        }
