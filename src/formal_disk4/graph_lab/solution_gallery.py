from __future__ import annotations

import json
import threading
from pathlib import Path
from typing import Any, Mapping

from formal_disk4.visualization.svg import geometric_solution_svg


class GeometrySolutionIndex:
    """Incremental in-memory index for the comparatively small solution JSONL."""

    def __init__(self, path: Path) -> None:
        self.path = path.resolve()
        self.lock = threading.RLock()
        self.offset = 0
        self.records: dict[str, Mapping[str, Any]] = {}
        self.svg_cache: dict[str, str] = {}

    def refresh(self) -> int:
        with self.lock:
            if not self.path.exists():
                return 0
            if self.path.stat().st_size < self.offset:
                self.offset = 0
                self.records.clear()
                self.svg_cache.clear()
            with self.path.open("rb") as stream:
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
                    try:
                        record = json.loads(raw.decode("utf-8"))
                    except (UnicodeDecodeError, json.JSONDecodeError):
                        continue
                    if not isinstance(record, Mapping):
                        continue
                    profile_id = record.get("formal_profile_id")
                    if isinstance(profile_id, str) and profile_id:
                        self.records[profile_id] = record
                        self.svg_cache.pop(profile_id, None)
            return len(self.records)

    def get(self, profile_id: str) -> Mapping[str, Any] | None:
        self.refresh()
        with self.lock:
            return self.records.get(profile_id)

    def svg(self, profile_id: str) -> str | None:
        self.refresh()
        with self.lock:
            cached = self.svg_cache.get(profile_id)
            if cached is not None:
                return cached
            record = self.records.get(profile_id)
            if record is None:
                return None
            rendered = geometric_solution_svg(record)
            self.svg_cache[profile_id] = rendered
            return rendered
