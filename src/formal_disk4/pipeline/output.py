from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any, Mapping


class JsonlWriter:
    def __init__(
        self,
        path: Path,
        flush_every: int = 1,
        *,
        append: bool = False,
        max_records: int | None = None,
    ) -> None:
        self.path = path
        self.path.parent.mkdir(parents=True, exist_ok=True)
        mode = "a" if append else "w"
        self.handle = path.open(mode, encoding="utf-8", buffering=1)
        self.flush_every = max(1, int(flush_every))
        self.max_records = None if max_records is None else max(0, int(max_records))
        self.count = 0
        self.dropped = 0
        if append and self.max_records is not None and path.exists():
            # Optional audit streams are globally capped across resumed sessions.
            # Stop counting as soon as the cap is reached.
            with path.open("r", encoding="utf-8", errors="replace") as existing:
                for _line in existing:
                    self.count += 1
                    if self.count >= self.max_records:
                        break

    def write(self, record: Mapping[str, Any]) -> bool:
        if self.max_records is not None and self.count >= self.max_records:
            self.dropped += 1
            return False
        self.handle.write(json.dumps(record, ensure_ascii=False, separators=(",", ":")) + "\n")
        self.count += 1
        if self.count % self.flush_every == 0:
            self.handle.flush()
        return True

    def close(self) -> None:
        if not self.handle.closed:
            self.handle.flush()
            self.handle.close()

    def __enter__(self) -> "JsonlWriter":
        return self

    def __exit__(self, *_args: object) -> None:
        self.close()


class NullJsonlWriter:
    count = 0
    dropped = 0
    path: Path | None = None

    def write(self, _record: Mapping[str, Any]) -> bool:
        return False

    def close(self) -> None:
        return None


def atomic_write_json(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    with temporary.open("w", encoding="utf-8") as handle:
        json.dump(payload, handle, indent=2, ensure_ascii=False)
        handle.write("\n")
    os.replace(temporary, path)
