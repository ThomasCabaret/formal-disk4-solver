from __future__ import annotations

import json
import threading
from collections import deque
from pathlib import Path
from typing import Any, Mapping

from formal_disk4.orchestration.catalog_diagrams import (
    build_catalog_schematic,
    catalog_schematic_svg,
)

from .space import DualGraphCandidate, build_dynamic_planar_map


def _permutation_cycles(permutation: tuple[int, ...] | None) -> str:
    if permutation is None:
        return "none"
    unseen = set(range(len(permutation)))
    cycles = []
    while unseen:
        seed = min(unseen)
        cycle = []
        current = seed
        while current in unseen:
            unseen.remove(current)
            cycle.append(current)
            current = permutation[current]
        cycles.append("(" + " ".join(f"T{tile}" for tile in cycle) + ")")
    return "".join(cycles)


class RecentStructureGallery:
    """Incremental tail index of graph/symmetry visits from observations JSONL."""

    def __init__(self, source: Path, *, capacity: int = 200) -> None:
        self.source = source.resolve()
        self.capacity = max(100, int(capacity))
        self.lock = threading.RLock()
        self.offset = 0
        self.source_line = 0
        self.items: deque[dict[str, object]] = deque()
        self.candidates: dict[str, DualGraphCandidate] = {}
        self.svg_cache: dict[str, str] = {}
        self._initialize_tail()

    @staticmethod
    def _complete_line_count(path: Path, size: int) -> int:
        count = 0
        remaining = max(0, int(size))
        with path.open("rb") as stream:
            while remaining:
                chunk = stream.read(min(1024 * 1024, remaining))
                if not chunk:
                    break
                count += chunk.count(b"\n")
                remaining -= len(chunk)
        return count

    def _tail(self, size: int) -> tuple[list[tuple[int, bytes]], int, int]:
        position = size
        chunks: list[bytes] = []
        newlines = 0
        with self.source.open("rb") as stream:
            while position > 0 and newlines <= self.capacity:
                amount = min(64 * 1024, position)
                position -= amount
                stream.seek(position)
                chunk = stream.read(amount)
                chunks.insert(0, chunk)
                newlines += chunk.count(b"\n")
        raw = b"".join(chunks)
        base = position
        if position > 0:
            boundary = raw.find(b"\n")
            if boundary < 0:
                return [], 0, 0
            base += boundary + 1
            raw = raw[boundary + 1 :]
        complete_end = raw.rfind(b"\n")
        if complete_end < 0:
            return [], base, 0
        complete = raw[: complete_end + 1]
        rows: list[tuple[int, bytes]] = []
        cursor = base
        for line in complete.splitlines(keepends=True):
            rows.append((cursor, line))
            cursor += len(line)
        return rows[-self.capacity :], base + complete_end + 1, len(rows)

    def _initialize_tail(self) -> None:
        with self.lock:
            if not self.source.exists():
                return
            # Count and tail one fixed byte snapshot. Appends that happen while
            # this runs remain after complete_offset and are picked up by the
            # normal incremental refresh, so live writes cannot skew visit IDs.
            snapshot_size = self.source.stat().st_size
            total_lines = self._complete_line_count(self.source, snapshot_size)
            rows, complete_offset, tail_line_count = self._tail(snapshot_size)
            first_line = total_lines - min(self.capacity, tail_line_count) + 1
            for index, (offset, raw) in enumerate(rows):
                self._ingest_raw(raw, first_line + index, offset)
            self.offset = complete_offset
            self.source_line = total_lines

    def _ingest_raw(self, raw: bytes, line_number: int, offset: int) -> None:
        try:
            record = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            return
        if not isinstance(record, Mapping) or not isinstance(
            record.get("candidate"), Mapping
        ):
            return
        try:
            candidate = DualGraphCandidate.from_dict(record["candidate"])
        except (KeyError, TypeError, ValueError):
            return
        visit_id = str(line_number)
        selection = record.get("selection", {})
        if not isinstance(selection, Mapping):
            selection = {}
        item = {
            "visit_id": visit_id,
            "line": line_number,
            "source_offset": offset,
            "generation": int(record.get("generation", 0) or 0),
            "graph_id": candidate.graph_id,
            "tile_count": candidate.tile_count,
            "edge_count": candidate.edge_count,
            "symmetry_order": candidate.symmetry_order,
            "imposed_permutation": (
                list(candidate.imposed_permutation)
                if candidate.imposed_permutation is not None
                else None
            ),
            "symmetry_cycles": _permutation_cycles(candidate.imposed_permutation),
            "source_symmetry": candidate.source_symmetry,
            "origin": candidate.origin,
            "mutation": candidate.mutation,
            "selection_mode": str(
                selection.get("selection_mode", selection.get("selection", "unknown"))
            ),
            "selection_score": selection.get("selection_score"),
            "stage": str(record.get("stage_name", "unknown")),
            "profile_count": int(record.get("profile_count", 0) or 0),
            "preview_url": f"/api/structure-svg?visit={visit_id}",
        }
        if len(self.items) >= self.capacity:
            removed = self.items.popleft()
            self.candidates.pop(str(removed["visit_id"]), None)
        self.items.append(item)
        self.candidates[visit_id] = candidate

    def refresh(self) -> int:
        with self.lock:
            if not self.source.exists():
                return 0
            if self.source.stat().st_size < self.offset:
                self.offset = 0
                self.source_line = 0
                self.items.clear()
                self.candidates.clear()
                self.svg_cache.clear()
                self._initialize_tail()
                return len(self.items)
            with self.source.open("rb") as stream:
                stream.seek(self.offset)
                while True:
                    line_offset = stream.tell()
                    raw = stream.readline()
                    if not raw:
                        break
                    if not raw.endswith(b"\n"):
                        stream.seek(line_offset)
                        break
                    self.offset = stream.tell()
                    self.source_line += 1
                    self._ingest_raw(raw, self.source_line, line_offset)
            return len(self.items)

    def recent(self, limit: int = 100) -> dict[str, object]:
        self.refresh()
        with self.lock:
            amount = min(self.capacity, max(1, int(limit)))
            selected = list(self.items)[-amount:]
            return {
                "requested": amount,
                "available": len(self.items),
                "latest_line": self.source_line,
                "items": list(reversed(selected)),
            }

    def svg(self, visit_id: str) -> str | None:
        self.refresh()
        with self.lock:
            candidate = self.candidates.get(str(visit_id))
            if candidate is None:
                return None
            cached = self.svg_cache.get(candidate.graph_id)
            if cached is not None:
                return cached
            planar_map = build_dynamic_planar_map(candidate).planar_map
            schematic = build_catalog_schematic(planar_map)
            rendered = catalog_schematic_svg(schematic)
            if len(self.svg_cache) >= 512:
                self.svg_cache.clear()
            self.svg_cache[candidate.graph_id] = rendered
            return rendered
