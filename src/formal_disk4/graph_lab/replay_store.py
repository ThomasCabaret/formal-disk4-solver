from __future__ import annotations

import hashlib
import json
import re
from collections import deque
from pathlib import Path
from typing import Any, Callable, Mapping, Sequence, TypeVar

from .mapping import MappingEvaluation, MappingProposal
from .run_store import GraphLabRunStore
from .specialization_model import SpecializationPoolObservation
from .weak_model import WeakOrderRolloutObservation


MAX_MAPPING_REPLAY_IN_MEMORY = 8192
MAX_WEAK_ORDER_REPLAY_IN_MEMORY = 8192
MAX_SPECIALIZATION_REPLAY_IN_MEMORY = 4096

_MAPPING_ID_PATTERN = re.compile(rb'"mapping_id"\s*:\s*"([^"]+)"')
_ACTION_MASK_PATTERN = re.compile(rb'"mask"\s*:\s*(-?\d+)')


def mapping_id_from_journal_line(line: bytes) -> str | None:
    match = _MAPPING_ID_PATTERN.search(line)
    return match.group(1).decode("ascii") if match is not None else None


def weak_trajectory_id_from_journal_line(line: bytes) -> str | None:
    mapping_id = mapping_id_from_journal_line(line)
    if mapping_id is None:
        return None
    masks = ",".join(
        match.group(1).decode("ascii") for match in _ACTION_MASK_PATTERN.finditer(line)
    )
    payload = f"{mapping_id}|{masks}".encode("ascii")
    return "wr-" + hashlib.sha256(payload).hexdigest()[:24]


def tail_jsonl(
    path: Path,
    limit: int,
    *,
    identity: Callable[[bytes], str | None] | None = None,
) -> tuple[list[dict[str, Any]], int, set[str]]:
    """Decode only the bounded replay tail while indexing the full journal."""

    if not path.exists():
        return [], 0, set()
    raw_tail: deque[bytes] = deque(maxlen=max(1, int(limit)))
    identities: set[str] = set()
    total = 0
    with path.open("rb") as stream:
        for line in stream:
            if not line.strip():
                continue
            raw_tail.append(line)
            if identity is not None:
                identifier = identity(line)
                if identifier is not None:
                    identities.add(identifier)
            total += 1
    records = []
    for line in raw_tail:
        value = json.loads(line)
        if isinstance(value, dict):
            records.append(value)
    return records, total, identities


ReplayItem = TypeVar("ReplayItem")


def extend_bounded_replay(
    replay: list[ReplayItem],
    additions: Sequence[ReplayItem],
    *,
    limit: int,
) -> None:
    replay.extend(additions)
    excess = len(replay) - max(1, int(limit))
    if excess > 0:
        del replay[:excess]


class GraphLabReplayStore:
    """Persistence adapter for the optional learned-policy replay journals."""

    def __init__(
        self,
        store: GraphLabRunStore,
        *,
        mapping_learning: Mapping[str, object],
        weak_order_learning: Mapping[str, object],
        specialization_learning: Mapping[str, object],
    ) -> None:
        self.store = store
        self.mapping_learning = mapping_learning
        self.weak_order_learning = weak_order_learning
        self.specialization_learning = specialization_learning

    def load_mappings(self) -> tuple[list[MappingEvaluation], set[str], int]:
        configured = max(
            1, int(self.mapping_learning.get("replay_examples", 50000))
        )
        values, total, seen_ids = tail_jsonl(
            self.store.path("mapping_observations.jsonl"),
            min(configured, MAX_MAPPING_REPLAY_IN_MEMORY),
            identity=mapping_id_from_journal_line,
        )
        return [MappingEvaluation.from_dict(value) for value in values], seen_ids, total

    def load_weak_orders(
        self,
    ) -> tuple[list[WeakOrderRolloutObservation], set[str], int]:
        configured = max(
            1, int(self.weak_order_learning.get("replay_rollouts", 50000))
        )
        values, total, seen_ids = tail_jsonl(
            self.store.path("weak_order_rollouts.jsonl"),
            min(configured, MAX_WEAK_ORDER_REPLAY_IN_MEMORY),
            identity=weak_trajectory_id_from_journal_line,
        )
        return (
            [WeakOrderRolloutObservation.from_dict(value) for value in values],
            seen_ids,
            total,
        )

    def load_specializations(
        self,
    ) -> tuple[list[SpecializationPoolObservation], int]:
        configured = max(
            1, int(self.specialization_learning.get("replay_pools", 20000))
        )
        limit = min(configured, MAX_SPECIALIZATION_REPLAY_IN_MEMORY)
        proposals: dict[str, MappingProposal] = {}
        pools: deque[SpecializationPoolObservation] = deque(maxlen=limit)
        total = 0
        for value in self.store.iter_jsonl("specialization_pools.jsonl"):
            raw_proposal = value.get("proposal")
            proposal = (
                MappingProposal.from_dict(raw_proposal)
                if isinstance(raw_proposal, Mapping)
                else proposals.get(str(value.get("mapping_id", "")))
            )
            if proposal is None:
                raise ValueError(
                    "Specialization journal references a mapping before its full record"
                )
            proposals[proposal.mapping_id] = proposal
            pools.append(
                SpecializationPoolObservation.from_dict(value, proposal=proposal)
            )
            total += 1
        return list(pools), total
