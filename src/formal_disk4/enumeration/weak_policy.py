from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol, Sequence, Tuple


@dataclass(frozen=True)
class WeakOrderStateView:
    """Immutable, solver-independent view of one weak-order decision state."""

    assignment_id: int
    path: Tuple[int, ...]
    counters: Tuple[int, ...]
    targets: Tuple[int, ...]
    block_count: int
    resolved_length_equations: int
    resolved_angle_equations: int
    available_mask: int
    reference_index: int
    cyclic_shift_half: bool = False

    @property
    def placed_occurrences(self) -> int:
        return sum(self.counters)

    @property
    def total_occurrences(self) -> int:
        return sum(self.targets)

    def to_dict(self) -> dict[str, object]:
        return {
            "assignment_id": self.assignment_id,
            "path": list(self.path),
            "counters": list(self.counters),
            "targets": list(self.targets),
            "block_count": self.block_count,
            "resolved_length_equations": self.resolved_length_equations,
            "resolved_angle_equations": self.resolved_angle_equations,
            "available_mask": self.available_mask,
            "reference_index": self.reference_index,
            "cyclic_shift_half": self.cyclic_shift_half,
        }

    @classmethod
    def from_dict(cls, payload: dict[str, object]) -> "WeakOrderStateView":
        return cls(
            assignment_id=int(payload["assignment_id"]),
            path=tuple(int(value) for value in payload.get("path", ())),  # type: ignore[arg-type]
            counters=tuple(int(value) for value in payload["counters"]),  # type: ignore[union-attr]
            targets=tuple(int(value) for value in payload["targets"]),  # type: ignore[union-attr]
            block_count=int(payload["block_count"]),
            resolved_length_equations=int(
                payload.get("resolved_length_equations", 0)
            ),
            resolved_angle_equations=int(
                payload.get("resolved_angle_equations", 0)
            ),
            available_mask=int(payload["available_mask"]),
            reference_index=int(payload["reference_index"]),
            cyclic_shift_half=bool(payload.get("cyclic_shift_half", False)),
        )


@dataclass(frozen=True)
class WeakOrderActionView:
    """One legal candidate for the next weak-order block."""

    mask: int
    next_counters: Tuple[int, ...]
    selected_count: int
    new_length_equations: int
    new_angle_equations: int

    def to_dict(self) -> dict[str, object]:
        return {
            "mask": self.mask,
            "next_counters": list(self.next_counters),
            "selected_count": self.selected_count,
            "new_length_equations": self.new_length_equations,
            "new_angle_equations": self.new_angle_equations,
        }

    @classmethod
    def from_dict(cls, payload: dict[str, object]) -> "WeakOrderActionView":
        return cls(
            mask=int(payload["mask"]),
            next_counters=tuple(
                int(value) for value in payload["next_counters"]  # type: ignore[union-attr]
            ),
            selected_count=int(payload["selected_count"]),
            new_length_equations=int(payload.get("new_length_equations", 0)),
            new_angle_equations=int(payload.get("new_angle_equations", 0)),
        )


class WeakOrderBranchPolicy(Protocol):
    """Optional Lab policy; production passes ``None`` and remains exhaustive."""

    def propose_masks(
        self,
        state: WeakOrderStateView,
        masks: Sequence[int],
    ) -> Sequence[int]:
        """Optionally restrict the experimental action pool before expansion."""

    def select_actions(
        self,
        state: WeakOrderStateView,
        actions: Sequence[WeakOrderActionView],
    ) -> Sequence[int]:
        """Return action masks in visit order; a rollout normally returns one."""
