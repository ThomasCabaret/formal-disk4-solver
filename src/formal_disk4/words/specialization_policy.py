from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol, Sequence, Tuple

from formal_disk4.enumeration.weak_orders import Placement

from .compile import CompiledWordCase
from .families import ExactFormalFamily, FamilySpecialization


@dataclass(frozen=True)
class SpecializationPoolStateView:
    """Immutable description of one word-case specialization decision."""

    assignment_id: int
    placement_id: int
    placement_block_count: int
    solver_variable_count: int
    equation_count: int
    interface_count: int
    outer_arc_count: int
    contour_literal_count: int
    family_count: int
    candidate_count: int
    placement_blocks: Tuple[Tuple[int, ...], ...]

    def to_dict(self) -> dict[str, object]:
        return {
            "assignment_id": self.assignment_id,
            "placement_id": self.placement_id,
            "placement_block_count": self.placement_block_count,
            "solver_variable_count": self.solver_variable_count,
            "equation_count": self.equation_count,
            "interface_count": self.interface_count,
            "outer_arc_count": self.outer_arc_count,
            "contour_literal_count": self.contour_literal_count,
            "family_count": self.family_count,
            "candidate_count": self.candidate_count,
            "placement_blocks": [list(block) for block in self.placement_blocks],
        }

    @classmethod
    def from_dict(cls, payload: dict[str, object]) -> "SpecializationPoolStateView":
        return cls(
            **{
                name: (
                    tuple(
                        tuple(int(value) for value in block)
                        for block in payload.get("placement_blocks", ())
                    )
                    if name == "placement_blocks"
                    else int(payload[name])
                )
                for name in cls.__dataclass_fields__
            }
        )


@dataclass(frozen=True)
class SpecializationActionView:
    """Numeric, graph-agnostic features of one family specialization."""

    index: int
    family_id: int
    family_kind: str
    residual_graph_nodes: int
    family_power_depth: int
    family_trace_length: int
    exponent_variable_count: int
    exponent_sum: int
    exponent_minimum: int
    exponent_maximum: int
    environment_variable_count: int
    total_word_literals: int
    maximum_word_literals: int
    distinct_word_count: int
    distinct_literal_variable_count: int
    inverse_literal_count: int
    empty_word_count: int
    environment_words: Tuple[Tuple[int, ...], ...]

    def to_dict(self) -> dict[str, object]:
        return {
            name: getattr(self, name) for name in self.__dataclass_fields__
        }

    @classmethod
    def from_dict(cls, payload: dict[str, object]) -> "SpecializationActionView":
        values = {
            name: (
                str(payload[name])
                if name == "family_kind"
                else tuple(
                    tuple(int(token) for token in word)
                    for word in payload.get("environment_words", ())
                )
                if name == "environment_words"
                else int(payload[name])
            )
            for name in cls.__dataclass_fields__
        }
        return cls(**values)  # type: ignore[arg-type]


@dataclass(frozen=True)
class SpecializationOutcomeView:
    """Observed result of attempting one specialization."""

    valid_profile: bool
    emitted: bool
    duplicate: bool
    stage: str
    reason: str | None
    elapsed_seconds: float
    formal_profile_id: str | None = None


class FamilySpecializationPolicy(Protocol):
    """Optional Lab policy; production passes ``None`` and keeps its order."""

    def select_specializations(
        self,
        state: SpecializationPoolStateView,
        actions: Sequence[SpecializationActionView],
    ) -> Sequence[int]:
        """Return unique legal action indices to visit in this bounded rollout.

        Omitting an index is local to this API request.  It must not create a
        persistent closed set; the experimental caller is responsible for
        full-support revisits.  Production passes no policy and stays
        exhaustive.
        """

    def observe_specialization(
        self,
        state: SpecializationPoolStateView,
        action: SpecializationActionView,
        outcome: SpecializationOutcomeView,
    ) -> None:
        """Receive the exact outcome after an attempted action."""


def specialization_pool_state(
    *,
    assignment_id: int,
    placement: Placement,
    compiled: CompiledWordCase,
    family_count: int,
    candidate_count: int,
) -> SpecializationPoolStateView:
    return SpecializationPoolStateView(
        assignment_id=int(assignment_id),
        placement_id=int(placement.placement_id),
        placement_block_count=len(placement.blocks),
        solver_variable_count=len(compiled.solver_variables),
        equation_count=len(compiled.effective_solver_equations),
        interface_count=len(compiled.interfaces),
        outer_arc_count=len(compiled.outer_arcs),
        contour_literal_count=len(compiled.contour_word),
        family_count=int(family_count),
        candidate_count=int(candidate_count),
        placement_blocks=tuple(
            tuple(int(value) for value in block) for block in placement.blocks
        ),
    )


def specialization_action(
    index: int,
    family: ExactFormalFamily,
    specialization: FamilySpecialization,
) -> SpecializationActionView:
    words = tuple(word for _variable, word in specialization.environment)
    literals = tuple(literal for word in words for literal in word)
    exponents = tuple(value for _name, value in specialization.exponent_assignment)
    # Family canonicalization names terminal variables by first occurrence.
    # Repeating that convention here gives the Lab an exact symbolic shape
    # without leaking graph-specific strings into the learning contract.
    literal_ids: dict[str, int] = {}
    environment_words = []
    for word in words:
        encoded = []
        for literal in word:
            token = literal_ids.setdefault(literal.variable, len(literal_ids) + 1)
            encoded.append(-token if literal.inverse else token)
        environment_words.append(tuple(encoded))
    return SpecializationActionView(
        index=int(index),
        family_id=int(family.family_id),
        family_kind=str(family.kind),
        residual_graph_nodes=int(family.residual_graph_nodes),
        family_power_depth=int(family.power_depth),
        family_trace_length=len(family.trace),
        exponent_variable_count=len(exponents),
        exponent_sum=sum(exponents),
        exponent_minimum=min(exponents, default=0),
        exponent_maximum=max(exponents, default=0),
        environment_variable_count=len(words),
        total_word_literals=len(literals),
        maximum_word_literals=max((len(word) for word in words), default=0),
        distinct_word_count=len(set(words)),
        distinct_literal_variable_count=len(
            {literal.variable for literal in literals}
        ),
        inverse_literal_count=sum(literal.inverse for literal in literals),
        empty_word_count=sum(not word for word in words),
        environment_words=tuple(environment_words),
    )
