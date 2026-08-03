from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Mapping

from .core import LabEvaluation, MappingSpace


@dataclass(frozen=True)
class DeepSeedEntry:
    candidate_id: str
    stage_index: int
    score: float
    status: str
    proposal_source: str
    proposal_strategy: str
    masks: tuple[int, ...]

    @classmethod
    def from_evaluation(cls, evaluation: LabEvaluation) -> "DeepSeedEntry":
        return cls(
            candidate_id=evaluation.candidate_id,
            stage_index=evaluation.stage_index,
            score=evaluation.score,
            status=evaluation.status,
            proposal_source=evaluation.proposal_source,
            proposal_strategy=evaluation.proposal_strategy,
            masks=evaluation.masks,
        )

    @classmethod
    def from_dict(cls, payload: Mapping[str, object]) -> "DeepSeedEntry":
        return cls(
            candidate_id=str(payload["candidate_id"]),
            stage_index=int(payload["stage_index"]),
            score=float(payload.get("score", payload["stage_index"])),
            status=str(payload.get("status", "rejected")),
            proposal_source=str(payload.get("proposal_source", "archive")),
            proposal_strategy=str(payload.get("proposal_strategy", "archive")),
            masks=tuple(int(value) for value in payload["masks"]),
        )

    def to_dict(self) -> dict[str, object]:
        return {
            "candidate_id": self.candidate_id,
            "stage_index": self.stage_index,
            "score": self.score,
            "status": self.status,
            "proposal_source": self.proposal_source,
            "proposal_strategy": self.proposal_strategy,
            "masks": list(self.masks),
        }


class DeepSeedBuffer:
    """Bounded persistent memory used only to generate local mutations."""

    def __init__(self, *, capacity: int, minimum_stage_index: int) -> None:
        self.capacity = max(1, int(capacity))
        self.minimum_stage_index = max(0, int(minimum_stage_index))
        self._entries: dict[str, DeepSeedEntry] = {}

    def __len__(self) -> int:
        return len(self._entries)

    @property
    def entries(self) -> tuple[DeepSeedEntry, ...]:
        return tuple(
            sorted(
                self._entries.values(),
                key=lambda item: (item.stage_index, item.score, item.candidate_id),
                reverse=True,
            )
        )

    @property
    def deepest_stage_index(self) -> int | None:
        return max((entry.stage_index for entry in self._entries.values()), default=None)

    def add_evaluation(self, evaluation: LabEvaluation) -> bool:
        if evaluation.status in {"timeout", "evaluation_error"}:
            return False
        return self.add(DeepSeedEntry.from_evaluation(evaluation))

    def add(self, entry: DeepSeedEntry) -> bool:
        if entry.stage_index < self.minimum_stage_index:
            return False
        previous = self._entries.get(entry.candidate_id)
        if previous is not None and (previous.stage_index, previous.score) >= (
            entry.stage_index,
            entry.score,
        ):
            return False
        self._entries[entry.candidate_id] = entry
        if len(self._entries) > 2 * self.capacity:
            self.finalize()
        return True

    def finalize(self) -> None:
        retained = self.entries[: self.capacity]
        self._entries = {entry.candidate_id: entry for entry in retained}

    def load_archive(self, path: Path, *, space: MappingSpace) -> dict[str, int]:
        scanned = eligible = invalid = 0
        if path.exists():
            with path.open("r", encoding="utf-8", errors="replace") as stream:
                for line in stream:
                    if not line.strip():
                        continue
                    try:
                        payload = json.loads(line)
                        if str(payload.get("case_id", space.case.case_id)) != space.case.case_id:
                            continue
                        entry = DeepSeedEntry.from_dict(payload)
                        space.mapping_feature_vector(entry.masks)
                    except (json.JSONDecodeError, KeyError, TypeError, ValueError):
                        invalid += 1
                        continue
                    scanned += 1
                    if entry.stage_index < self.minimum_stage_index:
                        continue
                    eligible += 1
                    self.add(entry)
        self.finalize()
        return {
            "scanned": scanned,
            "eligible": eligible,
            "invalid": invalid,
            "retained": len(self),
        }

    def to_dict(self) -> dict[str, object]:
        return {
            "capacity": self.capacity,
            "minimum_stage_index": self.minimum_stage_index,
            "retained": len(self),
            "deepest_stage_index": self.deepest_stage_index,
            "entries": [entry.to_dict() for entry in self.entries],
        }

    @classmethod
    def from_dict(cls, payload: Mapping[str, object]) -> "DeepSeedBuffer":
        result = cls(
            capacity=int(payload["capacity"]),
            minimum_stage_index=int(payload["minimum_stage_index"]),
        )
        for raw_entry in payload.get("entries", []):
            if isinstance(raw_entry, Mapping):
                result.add(DeepSeedEntry.from_dict(raw_entry))
        result.finalize()
        return result
