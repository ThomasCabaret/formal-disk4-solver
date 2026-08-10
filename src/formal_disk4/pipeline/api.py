from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
from typing import Any, Dict, Mapping, Sequence, Tuple

from formal_disk4.maps.base import PlanarMap
from formal_disk4.enumeration.weak_policy import WeakOrderBranchPolicy

from .filter_report import AssignmentFilterEvaluation, FilterReport
from .runner import SolverRunner


SOLVER_API_SCHEMA_VERSION = "formal-solver-api-v1"


@dataclass(frozen=True)
class AssignmentSelection:
    """Select raw contour mappings for one graph.

    ``raw_assignment_ids`` use the mixed-radix ids exposed by
    :class:`AssignmentEnumerator`, before the intrinsic-symmetry quotient.  A
    non-canonical selected id is therefore reported as rejected by the quotient
    instead of being silently replaced by another mapping.
    """

    map_name: str
    raw_assignment_ids: Tuple[int, ...]

    def __post_init__(self) -> None:
        normalized = tuple(int(item) for item in self.raw_assignment_ids)
        if not normalized:
            raise ValueError("raw_assignment_ids must not be empty")
        if len(set(normalized)) != len(normalized):
            raise ValueError("raw_assignment_ids must not contain duplicates")
        if any(item < 0 for item in normalized):
            raise ValueError("raw_assignment_ids must be non-negative")
        object.__setattr__(self, "map_name", str(self.map_name))
        object.__setattr__(self, "raw_assignment_ids", normalized)


@dataclass(frozen=True)
class SolverAPIRequest:
    """Typed input contract for a production-kernel evaluation.

    Limits and output/checkpoint behavior remain explicit in ``config``.  This
    is intentional: the API changes which mappings enter the solver, not the
    mathematical meaning or deterministic ordering of the production solver.
    """

    config: Mapping[str, Any]
    planar_maps: Tuple[PlanarMap, ...] | None = None
    assignments: Tuple[AssignmentSelection, ...] = ()
    weak_order_random_seed: int | None = None
    weak_order_branch_policy: WeakOrderBranchPolicy | None = None
    collect_learning_diagnostics: bool = False

    def assignment_ids_by_map(self) -> Dict[str, Tuple[int, ...]]:
        result: Dict[str, Tuple[int, ...]] = {}
        for selection in self.assignments:
            if selection.map_name in result:
                raise ValueError(
                    f"Duplicate AssignmentSelection for {selection.map_name!r}"
                )
            result[selection.map_name] = selection.raw_assignment_ids
        return result


@dataclass(frozen=True)
class SolverAPIResult:
    summary: Mapping[str, object]
    filters: FilterReport
    assignments: Tuple[AssignmentFilterEvaluation, ...] = ()

    @property
    def target_vector(self) -> Tuple[float | None, ...]:
        return self.filters.target_vector()

    def to_dict(self) -> Dict[str, object]:
        return {
            "schema_version": SOLVER_API_SCHEMA_VERSION,
            "summary": dict(self.summary),
            "filter_report": self.filters.to_dict(),
            "assignment_evaluations": [
                item.to_dict() for item in self.assignments
            ],
        }


class FormalSolverAPI:
    """Public facade around the exact production pipeline.

    It deliberately delegates to :class:`SolverRunner`; the Lab and the normal
    CLI therefore cannot drift into two subtly different formal solvers.
    """

    @staticmethod
    def evaluate(request: SolverAPIRequest) -> SolverAPIResult:
        config = deepcopy(dict(request.config))
        runner = SolverRunner(
            config,
            planar_maps=request.planar_maps,
            raw_assignment_ids_by_map=request.assignment_ids_by_map(),
            collect_assignment_reports=True,
            collect_learning_diagnostics=request.collect_learning_diagnostics,
            weak_order_random_seed=request.weak_order_random_seed,
            weak_order_branch_policy=request.weak_order_branch_policy,
        )
        summary = runner.run()
        counters = dict(
            dict(summary.get("statistics", {})).get("counters", {})
        )
        return SolverAPIResult(
            summary=summary,
            filters=FilterReport.from_counters(
                {str(name): int(value) for name, value in counters.items()}
            ),
            assignments=runner.assignment_reports,
        )


def evaluate_formal_search(
    config: Mapping[str, Any],
    *,
    planar_maps: Sequence[PlanarMap] | None = None,
    assignments: Sequence[AssignmentSelection] = (),
    weak_order_random_seed: int | None = None,
    weak_order_branch_policy: WeakOrderBranchPolicy | None = None,
    collect_learning_diagnostics: bool = False,
) -> SolverAPIResult:
    """Convenience function for clients that do not need request persistence."""

    return FormalSolverAPI.evaluate(
        SolverAPIRequest(
            config=config,
            planar_maps=(tuple(planar_maps) if planar_maps is not None else None),
            assignments=tuple(assignments),
            weak_order_random_seed=weak_order_random_seed,
            weak_order_branch_policy=weak_order_branch_policy,
            collect_learning_diagnostics=collect_learning_diagnostics,
        )
    )
