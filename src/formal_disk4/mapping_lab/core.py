from __future__ import annotations

import hashlib
import json
import math
import random
import time
from collections import Counter
from copy import deepcopy
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping, Sequence, Tuple

from formal_disk4.constraints.angle_lp import AngleFeasibilityOracle
from formal_disk4.constraints.length_lp import LengthFeasibilityOracle
from formal_disk4.enumeration.assignments import AssignmentEnumerator
from formal_disk4.enumeration.mapping_subdomain import MappingSubdomain
from formal_disk4.enumeration.weak_orders import Placement, WeakOrderEnumerator
from formal_disk4.maps.registry import build_map
from formal_disk4.orchestration.catalog import CaseCatalog, CaseDefinition
from formal_disk4.preword import (
    PrefixRadiusArcTopologyFilter,
    PrewordLinearInvariantFilter,
    PrewordPruningPipeline,
    RadiusArcTopologyFilter,
)
from formal_disk4.words.compile import compile_word_case
from formal_disk4.words.exact_partial import ExactPartialWordSolver, SolverLimits


LAB_SEMANTICS_VERSION = "mapping-lab-v1"
STAGES = (
    "generated",
    "mapping_subdomain",
    "exterior_arc_repetition",
    "prefix_topology",
    "length",
    "angle",
    "complete_topology",
    "preword_topology",
    "preword_linear",
    "word_solver",
    "word_family",
)


def _deep_merge(target: dict[str, Any], source: Mapping[str, Any]) -> None:
    for key, value in source.items():
        if isinstance(value, Mapping) and isinstance(target.get(key), dict):
            _deep_merge(target[key], value)
        else:
            target[key] = deepcopy(value)


def load_case_search_config(case: CaseDefinition) -> dict[str, Any]:
    payload = json.loads(case.config_for("search").read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("The case search configuration must be a JSON object")
    _deep_merge(payload, case.overrides_for("search"))
    payload["maps"] = [case.map_name]
    return payload


@dataclass(frozen=True)
class MappingCandidate:
    candidate_id: str
    blocks: Tuple[Tuple[int, ...], ...]
    masks: Tuple[int, ...]
    proposal_source: str
    proposal_strategy: str

    def to_dict(self, occurrence_names: Sequence[str]) -> dict[str, object]:
        return {
            "candidate_id": self.candidate_id,
            "proposal_source": self.proposal_source,
            "proposal_strategy": self.proposal_strategy,
            "masks": list(self.masks),
            "blocks": [
                [occurrence_names[item] for item in block]
                for block in self.blocks
            ],
        }


@dataclass(frozen=True)
class LabEvaluation:
    candidate_id: str
    proposal_source: str
    proposal_strategy: str
    status: str
    terminal_stage: str
    stage_index: int
    score: float
    reason: str
    witness: Tuple[Tuple[str, str], ...]
    elapsed_seconds: float
    length_margin: float | None
    angle_margin: float | None
    events: Tuple[Tuple[str, int], ...]
    masks: Tuple[int, ...]
    blocks: Tuple[Tuple[int, ...], ...]
    word_summary: Mapping[str, object] | None = None

    def to_dict(self, occurrence_names: Sequence[str]) -> dict[str, object]:
        return {
            "schema_version": "mapping-lab-evaluation-v1",
            "candidate_id": self.candidate_id,
            "proposal_source": self.proposal_source,
            "proposal_strategy": self.proposal_strategy,
            "status": self.status,
            "terminal_stage": self.terminal_stage,
            "stage_index": self.stage_index,
            "score": self.score,
            "reason": self.reason,
            "witness": dict(self.witness),
            "elapsed_seconds": self.elapsed_seconds,
            "length_margin": self.length_margin,
            "angle_margin": self.angle_margin,
            "events": dict(self.events),
            "masks": list(self.masks),
            "blocks": [
                [occurrence_names[item] for item in block]
                for block in self.blocks
            ],
            "word_summary": dict(self.word_summary or {}),
        }

    @classmethod
    def timeout(cls, candidate: MappingCandidate, seconds: float) -> "LabEvaluation":
        return cls(
            candidate_id=candidate.candidate_id,
            proposal_source=candidate.proposal_source,
            proposal_strategy=candidate.proposal_strategy,
            status="timeout",
            terminal_stage="evaluation_timeout",
            stage_index=0,
            score=0.0,
            reason=f"hard timeout after {seconds:.3f}s",
            witness=(),
            elapsed_seconds=float(seconds),
            length_margin=None,
            angle_margin=None,
            events=(),
            masks=candidate.masks,
            blocks=candidate.blocks,
        )

    @classmethod
    def error(cls, candidate: MappingCandidate, reason: str) -> "LabEvaluation":
        return cls(
            candidate_id=candidate.candidate_id,
            proposal_source=candidate.proposal_source,
            proposal_strategy=candidate.proposal_strategy,
            status="evaluation_error",
            terminal_stage="evaluation_error",
            stage_index=0,
            score=0.0,
            reason=str(reason),
            witness=(),
            elapsed_seconds=0.0,
            length_margin=None,
            angle_margin=None,
            events=(),
            masks=candidate.masks,
            blocks=candidate.blocks,
        )


class MappingSpace:
    """Construct complete imposed-cyclic mappings without DFS enumeration."""

    def __init__(self, root: Path | str, case_id: str) -> None:
        self.root = Path(root).resolve()
        self.case = CaseCatalog.load(self.root).get(case_id)
        self.search_config = load_case_search_config(self.case)
        enumeration = self.search_config["enumeration"]
        raw_subdomain = enumeration.get("mapping_subdomain")
        self.planar_map = build_map(self.case.map_name)
        self.assignments = AssignmentEnumerator(
            self.planar_map,
            allow_reflections=bool(enumeration.get("allow_reflections", True)),
            symmetry_mode=str(enumeration.get("symmetry_mode", "off")),
        )
        self.subdomain = MappingSubdomain.from_config(
            self.planar_map,
            self.assignments.occurrence_names,
            raw_subdomain,
        )
        if self.subdomain is None:
            raise ValueError("The mapping lab prototype requires mapping_subdomain")
        assignment_ids = self.subdomain.assignment_ids(self.assignments)
        if len(assignment_ids) != 1:
            raise ValueError(
                "The first mapping lab prototype requires exactly one contour "
                f"assignment; this case selects {len(assignment_ids)}"
            )
        self.assignment = self.assignments.assignment_at(assignment_ids[0])
        if self.subdomain.cyclic_shift_split is None:
            raise ValueError(
                "The first mapping lab prototype requires a fixed cyclic_shift_split"
            )
        cyclic = enumeration.get("cyclic_shift_equivariance", {})
        if not bool(cyclic.get("enabled", False)):
            raise ValueError("The mapping lab prototype requires cyclic-shift symmetry")
        self.transform = self.assignments.transform_for_automorphism(
            str(cyclic["automorphism"])
        )
        self.split = self.subdomain.cyclic_shift_split
        self.prefixes = tuple(
            tuple(sequence[: self.split[index]])
            for index, sequence in enumerate(self.assignment.sequences)
        )
        self.piece_count = len(self.assignment.piece_names)
        self.reference_index = self.assignment.piece_names.index(
            self.planar_map.reference_piece
        )
        fingerprint_payload = {
            "version": LAB_SEMANTICS_VERSION,
            "case_id": case_id,
            "map": self.planar_map.to_dict(),
            "enumeration": enumeration,
            "filters": self.search_config.get("filters", {}),
        }
        encoded = json.dumps(
            fingerprint_payload, sort_keys=True, separators=(",", ":")
        ).encode("utf-8")
        self.fingerprint = hashlib.sha256(encoded).hexdigest()

    def sample(
        self,
        rng: random.Random,
        *,
        reference_masks: Sequence[int] | None = None,
        mutation_prefix_fraction: float = 1.0,
        proposal_source: str = "uniform",
        proposal_strategy: str = "uniform",
    ) -> MappingCandidate | None:
        counters = tuple(0 for _ in self.prefixes)
        half_blocks: list[Tuple[int, ...]] = []
        masks: list[int] = []
        mutation_index = None
        if reference_masks:
            mutation_limit = max(
                1,
                min(
                    len(reference_masks),
                    math.ceil(
                        len(reference_masks)
                        * min(1.0, max(0.0, mutation_prefix_fraction))
                    ),
                ),
            )
            mutation_index = rng.randrange(mutation_limit)
        while counters != self.split:
            available = 0
            for piece_index, (counter, sequence) in enumerate(
                zip(counters, self.prefixes)
            ):
                if counter < len(sequence):
                    available |= 1 << piece_index
            valid = []
            for mask in range(1, available + 1):
                if mask & ~available:
                    continue
                if not half_blocks and not mask & (1 << self.reference_index):
                    continue
                if not self.subdomain.allows_next_block(
                    counters,
                    mask,
                    self.assignment.sequences,
                    self.split,
                ):
                    continue
                valid.append(mask)
            if not valid:
                return None
            block_index = len(half_blocks)
            if mutation_index is not None and block_index < mutation_index:
                if block_index >= len(reference_masks):
                    return None
                mask = int(reference_masks[block_index])
                if mask not in valid:
                    return None
            elif mutation_index is not None and block_index == mutation_index:
                reference_mask = int(reference_masks[block_index])
                alternatives = [mask for mask in valid if mask != reference_mask]
                if not alternatives:
                    return None
                mask = int(rng.choice(tuple(alternatives)))
            else:
                mask = int(rng.choice(tuple(valid)))
            block = tuple(
                sorted(
                    self.prefixes[piece_index][counters[piece_index]]
                    for piece_index in range(self.piece_count)
                    if mask & (1 << piece_index)
                )
            )
            half_blocks.append(block)
            masks.append(mask)
            counters = tuple(
                counter + (1 if mask & (1 << piece_index) else 0)
                for piece_index, counter in enumerate(counters)
            )

        full_blocks: list[Tuple[int, ...]] = []
        current = tuple(half_blocks)
        for _ in range(self.subdomain.cyclic_action_order):
            full_blocks.extend(current)
            current = tuple(
                tuple(
                    sorted(self.transform.map_occurrence_id(item) for item in block)
                )
                for block in current
            )
        blocks = tuple(full_blocks)
        if not self.subdomain.allows_leaf(blocks):
            return None
        encoded = json.dumps(blocks, separators=(",", ":")).encode("utf-8")
        candidate_id = "mc-" + hashlib.sha256(encoded).hexdigest()[:24]
        return MappingCandidate(
            candidate_id=candidate_id,
            blocks=blocks,
            masks=tuple(masks),
            proposal_source=str(proposal_source),
            proposal_strategy=str(proposal_strategy),
        )

    @property
    def mapping_feature_dimension(self) -> int:
        occurrence_count = sum(self.split)
        pair_count = occurrence_count * (occurrence_count - 1) // 2
        return occurrence_count + 3 * pair_count + 1

    def mapping_feature_vector(self, masks: Sequence[int]) -> tuple[float, ...]:
        """Encode the complete weak order without depending on its block count."""
        offsets: list[int] = []
        offset = 0
        for count in self.split:
            offsets.append(offset)
            offset += count
        ranks = [-1] * offset
        counters = [0] * len(self.split)
        for block_index, raw_mask in enumerate(masks):
            mask = int(raw_mask)
            if mask <= 0:
                raise ValueError("mapping masks must be non-empty")
            for piece_index, limit in enumerate(self.split):
                if not mask & (1 << piece_index):
                    continue
                counter = counters[piece_index]
                if counter >= limit:
                    raise ValueError("mapping mask exceeds its occurrence split")
                ranks[offsets[piece_index] + counter] = block_index
                counters[piece_index] += 1
        if tuple(counters) != self.split or any(rank < 0 for rank in ranks):
            raise ValueError("mapping masks do not complete the occurrence split")
        denominator = max(1, len(masks) - 1)
        features: list[float] = [rank / denominator for rank in ranks]
        for left in range(len(ranks)):
            for right in range(left + 1, len(ranks)):
                relation = 0 if ranks[left] < ranks[right] else 1 if ranks[left] == ranks[right] else 2
                features.extend(
                    1.0 if relation == index else 0.0 for index in range(3)
                )
        features.append(len(masks) / max(1, len(ranks)))
        if len(features) != self.mapping_feature_dimension:
            raise AssertionError("mapping feature dimension mismatch")
        return tuple(features)


class CompleteMappingEvaluator:
    """Thin adapter around the production filters for one complete mapping."""

    def __init__(
        self,
        space: MappingSpace,
        evaluation_config: Mapping[str, Any] | None = None,
    ) -> None:
        self.space = space
        self.config = dict(evaluation_config or {})
        search = space.search_config
        enumeration = search["enumeration"]
        tolerance = float(enumeration.get("lp_tolerance", 1e-9))
        preword_config = search.get("filters", {}).get("preword_pruning", {})
        topology_config = preword_config.get("topology", {})
        linear_config = preword_config.get("linear_invariants", {})
        self._events: Counter[str] = Counter()
        prefix = PrefixRadiusArcTopologyFilter(
            space.planar_map,
            space.assignment,
            tolerance=tolerance,
            enable_endpoint_crossing=bool(
                topology_config.get("enable_endpoint_crossing", True)
            ),
            max_intervals=int(topology_config.get("max_intervals", 1024)),
        )
        self.enumerator = WeakOrderEnumerator(
            planar_map=space.planar_map,
            assignment=space.assignment,
            occurrence_names=space.assignments.occurrence_names,
            length_oracle=LengthFeasibilityOracle(tolerance=tolerance),
            angle_oracle=AngleFeasibilityOracle(tolerance=tolerance),
            symmetry_mode=str(enumeration.get("symmetry_mode", "off")),
            enable_length_filter=bool(
                enumeration.get("enable_length_filter", True)
            ),
            enable_angle_filter=bool(enumeration.get("enable_angle_filter", True)),
            enable_exterior_arc_repetition_filter=bool(
                enumeration.get("exterior_arc_repetition", {}).get("enabled", True)
            ),
            event_sink=self._record_event,
            track_exact_leaf_mass=False,
            required_cyclic_shift_transform=space.transform,
            prefix_topology_filter=prefix,
            mapping_subdomain=space.subdomain,
        )
        self.preword = PrewordPruningPipeline(
            topology_filter=RadiusArcTopologyFilter(
                tolerance=tolerance,
                enable_endpoint_crossing=bool(
                    topology_config.get("enable_endpoint_crossing", True)
                ),
                max_intervals=int(topology_config.get("max_intervals", 1024)),
            ),
            linear_filter=PrewordLinearInvariantFilter(
                tolerance=tolerance,
                enable_radius_measures=bool(
                    linear_config.get("enable_radius_measures", True)
                ),
                enable_smooth_turns=bool(
                    linear_config.get("enable_smooth_turns", True)
                ),
                enable_point_turns=bool(
                    linear_config.get("enable_point_turns", True)
                ),
                enforce_global_point_turn_balance=bool(
                    linear_config.get("enforce_global_point_turn_balance", True)
                ),
                enable_isoperimetric=bool(
                    linear_config.get("enable_isoperimetric", True)
                ),
                sqrt_upper_bound_denominator=int(
                    linear_config.get("sqrt_upper_bound_denominator", 1000)
                ),
            ),
            enable_topology=bool(topology_config.get("enabled", True)),
            enable_linear_invariants=bool(linear_config.get("enabled", True)),
        )

    def _record_event(self, name: str, amount: int = 1) -> None:
        self._events[name] += int(amount)

    @staticmethod
    def _event_reason(events: Mapping[str, int], prefix: str) -> str:
        options = [
            name[len(prefix) :]
            for name, amount in events.items()
            if amount and name.startswith(prefix) and "witness_" not in name
        ]
        return sorted(options)[0] if options else prefix.rstrip("_")

    @staticmethod
    def _event_witness(
        events: Mapping[str, int], prefix: str
    ) -> Tuple[Tuple[str, str], ...]:
        options = sorted(
            name[len(prefix) :]
            for name, amount in events.items()
            if amount and name.startswith(prefix)
        )
        return (("counter_witness", options[0]),) if options else ()

    def _leaf_rejection(self, events: Mapping[str, int]) -> tuple[str, str, tuple]:
        if events.get("mapping_subdomain_pruned_leaves"):
            return "mapping_subdomain", "mapping subdomain leaf constraint", ()
        if events.get("exterior_arc_repetition_pruned_nodes"):
            return "exterior_arc_repetition", "exterior arc repetition", ()
        if events.get("symmetry_pruned_leaves"):
            return "mapping_subdomain", "intrinsic symmetry quotient", ()
        if events.get("prefix_topology_pruned_nodes"):
            return (
                "prefix_topology",
                self._event_reason(events, "prefix_topology_rejection_"),
                self._event_witness(
                    events, "prefix_topology_rejection_witness_"
                ),
            )
        if events.get("length_pruned_nodes"):
            return "length", "length feasibility", ()
        if events.get("angle_pruned_nodes"):
            return "angle", "angle feasibility", ()
        if events.get("complete_topology_pruned_placements"):
            return (
                "complete_topology",
                self._event_reason(events, "complete_topology_rejection_"),
                self._event_witness(
                    events, "complete_topology_rejection_witness_"
                ),
            )
        return "generated", "complete mapping produced no placement", ()

    def evaluate(self, candidate: MappingCandidate) -> LabEvaluation:
        started = time.perf_counter()
        self._events = Counter()
        placements = tuple(
            self.enumerator._evaluate_cyclic_leaf(  # isolated production adapter
                candidate.blocks,
                path=candidate.masks,
                counters=self.space.split,
            )
        )
        events = dict(self._events)
        if not placements:
            stage, reason, witness = self._leaf_rejection(events)
            return self._result(
                candidate,
                status="rejected",
                stage=stage,
                reason=reason,
                witness=witness,
                started=started,
                events=events,
            )
        placement = placements[0]
        compiled = compile_word_case(self.space.planar_map, placement)
        preword = self.preword.analyze(
            self.space.planar_map, placement, compiled
        )
        if not preword.topology.feasible:
            return self._result(
                candidate,
                status="rejected",
                stage="preword_topology",
                reason=preword.reason,
                witness=preword.topology.rejection_witness,
                started=started,
                events=events,
                placement=placement,
            )
        if not preword.feasible:
            return self._result(
                candidate,
                status="rejected",
                stage="preword_linear",
                reason=preword.reason,
                witness=(),
                started=started,
                events=events,
                placement=placement,
            )
        if not bool(self.config.get("enable_word_solver", False)):
            return self._result(
                candidate,
                status="passed",
                stage="word_solver",
                reason="preword filters passed; word solver disabled",
                witness=(),
                started=started,
                events=events,
                placement=placement,
            )
        return self._evaluate_word_case(
            candidate, placement, compiled, started, events
        )

    def _evaluate_word_case(
        self,
        candidate: MappingCandidate,
        placement: Placement,
        compiled: Any,
        started: float,
        events: Mapping[str, int],
    ) -> LabEvaluation:
        solver = ExactPartialWordSolver(
            compiled.effective_solver_equations,
            compiled.solver_variables,
            contour_variables=compiled.atomic_variables,
        )
        seconds = max(0.0, float(self.config.get("word_seconds", 2.0)))
        deadline = time.perf_counter() + seconds
        limits = SolverLimits(
            max_graph_nodes=int(self.config.get("max_graph_nodes", 1000)),
            max_graph_edges=int(self.config.get("max_graph_edges", 4000)),
            max_families=int(self.config.get("max_families", 4)),
            max_expression_nodes=int(
                self.config.get("max_expression_nodes", 2000)
            ),
            max_terminal_contour_segments=int(
                self.config.get("max_terminal_contour_segments", 40)
            ),
            max_residual_literals=int(
                self.config.get("max_residual_literals", 2000)
            ),
        )
        families = list(
            solver.solve(
                limits,
                stop_predicate=lambda: time.perf_counter() >= deadline,
            )
        )
        summary = solver.last_summary.to_dict()
        summary["families"] = [family.to_dict() for family in families]
        if families:
            return self._result(
                candidate,
                status="word_family",
                stage="word_family",
                reason=f"{len(families)} word family/families emitted",
                witness=(),
                started=started,
                events=events,
                placement=placement,
                word_summary=summary,
            )
        status = "proved_unsat" if solver.last_summary.exact_unsat else "deferred"
        return self._result(
            candidate,
            status=status,
            stage="word_solver",
            reason=solver.last_summary.status,
            witness=(),
            started=started,
            events=events,
            placement=placement,
            word_summary=summary,
        )

    @staticmethod
    def _result(
        candidate: MappingCandidate,
        *,
        status: str,
        stage: str,
        reason: str,
        witness: Sequence[tuple[str, str]],
        started: float,
        events: Mapping[str, int],
        placement: Placement | None = None,
        word_summary: Mapping[str, object] | None = None,
    ) -> LabEvaluation:
        stage_index = STAGES.index(stage)
        length_margin = placement.length_margin if placement is not None else None
        angle_margin = placement.angle_margin if placement is not None else None
        margin_bonus = 0.0
        if length_margin is not None and angle_margin is not None:
            margin_bonus = min(
                0.09,
                0.01 * math.log1p(max(0.0, length_margin + angle_margin)),
            )
        return LabEvaluation(
            candidate_id=candidate.candidate_id,
            proposal_source=candidate.proposal_source,
            proposal_strategy=candidate.proposal_strategy,
            status=status,
            terminal_stage=stage,
            stage_index=stage_index,
            score=float(stage_index) + margin_bonus,
            reason=reason,
            witness=tuple((str(key), str(value)) for key, value in witness),
            elapsed_seconds=time.perf_counter() - started,
            length_margin=length_margin,
            angle_margin=angle_margin,
            events=tuple(sorted((str(key), int(value)) for key, value in events.items())),
            masks=candidate.masks,
            blocks=candidate.blocks,
            word_summary=word_summary,
        )
