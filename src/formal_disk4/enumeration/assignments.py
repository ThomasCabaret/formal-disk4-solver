from __future__ import annotations

from dataclasses import dataclass
from itertools import product
from typing import Dict, Iterator, List, Sequence, Tuple

from formal_disk4.maps.base import MapAutomorphism, Occurrence, PlanarMap

from .symmetry import MappingSymmetryQuotient, SymmetryAction


def rotate(values: Sequence[Occurrence], offset: int) -> Tuple[Occurrence, ...]:
    values = tuple(values)
    if not values:
        return ()
    offset %= len(values)
    return values[offset:] + values[:offset]


def anchored_reverse(values: Sequence[Occurrence]) -> Tuple[Occurrence, ...]:
    """Reverse cyclic orientation while keeping the cut occurrence first."""
    values = tuple(values)
    if len(values) <= 1:
        return values
    return (values[0],) + tuple(reversed(values[1:]))


def cyclic_orientation_phase(
    sequence: Sequence[Occurrence], base: Sequence[Occurrence]
) -> Tuple[int, int]:
    sequence = tuple(sequence)
    base = tuple(base)
    for phase in range(len(base)):
        if sequence == rotate(base, phase):
            return 1, phase
    reversed_base = tuple(reversed(base))
    for phase in range(len(base)):
        if sequence == rotate(reversed_base, phase):
            return -1, phase
    raise ValueError("Sequence is neither a rotation nor a reversed rotation of its base cycle")


@dataclass(frozen=True)
class AssignmentTransform:
    automorphism_name: str
    piece_map: Tuple[int, ...]
    occurrence_map: Tuple[int, ...]
    reverse_cycle: bool

    def map_occurrence_id(self, occurrence_id: int) -> int:
        return self.occurrence_map[occurrence_id]


@dataclass(frozen=True)
class ContourAssignment:
    assignment_id: int
    piece_names: Tuple[str, ...]
    sequences: Tuple[Tuple[int, ...], ...]
    orientation_signs: Tuple[int, ...]
    cyclic_offsets: Tuple[int, ...]
    stabilizer: Tuple[AssignmentTransform, ...]
    canonical_key: Tuple[Tuple[int, ...], ...]
    required_equivariance: str | None = None

    def sequence_for_piece_index(self, piece_index: int) -> Tuple[int, ...]:
        return self.sequences[piece_index]

    def to_dict(self, occurrence_names: Sequence[str]) -> Dict[str, object]:
        return {
            "assignment_id": self.assignment_id,
            "piece_sequences": {
                piece: [occurrence_names[index] for index in sequence]
                for piece, sequence in zip(self.piece_names, self.sequences)
            },
            "orientation_signs": dict(zip(self.piece_names, self.orientation_signs)),
            "cyclic_offsets": dict(zip(self.piece_names, self.cyclic_offsets)),
            "cyclic_offset_note": "Index of the first occurrence after the global prototype cut; not a geometric phase or angle.",
            "stabilizer_size": len(self.stabilizer),
            "incremental_stabilizer_size": sum(
                1 for transform in self.stabilizer if not transform.reverse_cycle
            ),
            "required_equivariance": self.required_equivariance,
        }


class AssignmentEnumerator:
    """Enumerate phase/orientation assignments with a lazy symmetry quotient.

    QUOTIENT JUSTIFICATION: intrinsic map automorphisms retain one canonical
    representative of each equivalent assignment orbit.

    SEARCH-DOMAIN RESTRICTION: ``required_equivariance`` is instead a symmetry
    imposed by the catalog case. It deliberately searches only assignments
    fixed by that action and must not be described as an unrestricted proof.
    """

    def __init__(
        self,
        planar_map: PlanarMap,
        allow_reflections: bool = True,
        symmetry_mode: str = "incremental",
        required_equivariance: str | None = None,
        required_equivariance_on_weak_orders: bool = True,
    ) -> None:
        if symmetry_mode not in {"off", "assignment", "incremental"}:
            raise ValueError("symmetry_mode must be off, assignment, or incremental")
        self.planar_map = planar_map
        self.allow_reflections = allow_reflections
        self.symmetry_mode = symmetry_mode
        self.required_equivariance = required_equivariance
        self.required_equivariance_on_weak_orders = bool(
            required_equivariance_on_weak_orders
        )
        self.piece_names = tuple(piece.name for piece in planar_map.pieces)
        self.piece_index = {name: index for index, name in enumerate(self.piece_names)}
        self.occurrences = planar_map.occurrences()
        self.occurrence_index = {
            occurrence: index for index, occurrence in enumerate(self.occurrences)
        }
        self.occurrence_names = tuple(occurrence.name for occurrence in self.occurrences)
        self.base_sequences = tuple(
            tuple(
                self.occurrence_index[Occurrence(piece.name, vertex)]
                for vertex in piece.contour_vertices
            )
            for piece in planar_map.pieces
        )
        self.reference_index = self.piece_index[planar_map.reference_piece]
        self.mapping_symmetry = MappingSymmetryQuotient(
            planar_map,
            required_equivariance=required_equivariance,
            required_equivariance_on_weak_orders=(
                self.required_equivariance_on_weak_orders
            ),
        )
        self.transforms = self._build_assignment_transforms()
        self._required_automorphism = self._resolve_required_automorphism()
        self._required_occurrence_map, self._required_piece_map = (
            self._build_required_maps()
            if self._required_automorphism is not None
            else ((), ())
        )
        self._equivariance_piece_orbits = self._build_equivariance_piece_orbits()

    @property
    def symmetry_enabled(self) -> bool:
        return self.symmetry_mode != "off"

    def _piece_options(self) -> Tuple[Tuple[Tuple[int, ...], ...], ...]:
        options: List[Tuple[Tuple[int, ...], ...]] = []
        for piece_index, base in enumerate(self.base_sequences):
            piece_options: List[Tuple[int, ...]] = []
            signs = (
                (1,)
                if piece_index == self.reference_index or not self.allow_reflections
                else (1, -1)
            )
            for sign in signs:
                oriented = base if sign == 1 else tuple(reversed(base))
                phases = (
                    (0,)
                    if (
                        self.symmetry_enabled
                        and self.mapping_symmetry.complete_mapping_quotient_enabled
                        and piece_index == self.reference_index
                    )
                    else range(len(base))
                )
                for phase in phases:
                    piece_options.append(tuple(oriented[phase:] + oriented[:phase]))
            options.append(tuple(piece_options))
        return tuple(options)

    def _resolve_required_automorphism(self) -> MapAutomorphism | None:
        if self.required_equivariance is None:
            return None
        for automorphism in self.planar_map.automorphisms:
            if automorphism.name == self.required_equivariance:
                return automorphism
        raise ValueError(
            f"Unknown required equivariance {self.required_equivariance!r} for map "
            f"{self.planar_map.name!r}"
        )

    def _build_required_maps(self) -> Tuple[Tuple[int, ...], Tuple[int, ...]]:
        assert self._required_automorphism is not None
        occurrence_map = tuple(
            self.occurrence_index[self._required_automorphism.map_occurrence(occurrence)]
            for occurrence in self.occurrences
        )
        piece_map = tuple(
            self.piece_index[self._required_automorphism.map_piece(piece_name)]
            for piece_name in self.piece_names
        )
        return occurrence_map, piece_map

    def _build_equivariance_piece_orbits(self) -> Tuple[Tuple[int, ...], ...]:
        if self._required_automorphism is None:
            return ()
        unseen = set(range(len(self.piece_names)))
        orbits: List[Tuple[int, ...]] = []
        while unseen:
            seed = min(unseen)
            orbit: List[int] = []
            current = seed
            while current not in orbit:
                orbit.append(current)
                unseen.discard(current)
                current = self._required_piece_map[current]
            if current != seed:
                raise ValueError("Required equivariance piece map is not a permutation cycle")
            if self.reference_index in orbit:
                offset = orbit.index(self.reference_index)
                orbit = orbit[offset:] + orbit[:offset]
            orbits.append(tuple(orbit))
        return tuple(orbits)

    @property
    def equivariance_piece_orbits(self) -> Tuple[Tuple[int, ...], ...]:
        return self._equivariance_piece_orbits

    def _equivariant_sequences_from_choices(
        self, choices: Sequence[Tuple[int, ...]]
    ) -> Tuple[Tuple[int, ...], ...]:
        # A required map rotation determines every copy in a piece orbit from
        # one representative. This is a search assumption, not a symmetry quotient.
        sequences: List[Tuple[int, ...] | None] = [None] * len(self.piece_names)
        for orbit, representative_sequence in zip(
            self._equivariance_piece_orbits, choices
        ):
            current_sequence = tuple(representative_sequence)
            for piece_index in orbit:
                existing = sequences[piece_index]
                if existing is not None and existing != current_sequence:
                    raise ValueError("Inconsistent required-equivariance assignment")
                sequences[piece_index] = current_sequence
                current_sequence = tuple(
                    self._required_occurrence_map[item] for item in current_sequence
                )
            if current_sequence != representative_sequence:
                raise ValueError(
                    "Required automorphism does not close the chosen contour sequence "
                    "around its piece orbit"
                )
        output = tuple(item for item in sequences if item is not None)
        if len(output) != len(self.piece_names):
            raise RuntimeError("Incomplete required-equivariance assignment")
        return output

    def _raw_sequences(self) -> Iterator[Tuple[Tuple[int, ...], ...]]:
        options = self._piece_options()
        if self._required_automorphism is None:
            yield from product(*options)
            return
        representative_options = tuple(
            options[orbit[0]] for orbit in self._equivariance_piece_orbits
        )
        for choices in product(*representative_options):
            yield self._equivariant_sequences_from_choices(choices)

    @staticmethod
    def _assignment_transform(action: SymmetryAction) -> AssignmentTransform:
        return AssignmentTransform(
            automorphism_name=action.name,
            piece_map=action.piece_permutation,
            occurrence_map=action.occurrence_permutation,
            reverse_cycle=action.orientation_sign == -1,
        )

    def _build_assignment_transforms(self) -> Tuple[AssignmentTransform, ...]:
        actions = (
            self.mapping_symmetry.assignment_group
            if self.symmetry_enabled
            else (
                next(
                    action
                    for action in self.mapping_symmetry.group
                    if action.piece_permutation
                    == tuple(range(len(self.piece_names)))
                    and action.vertex_permutation
                    == tuple(range(len(self.planar_map.vertices)))
                ),
            )
        )
        return tuple(self._assignment_transform(action) for action in actions)

    def apply_transform(
        self,
        sequences: Tuple[Tuple[int, ...], ...],
        transform: AssignmentTransform,
    ) -> Tuple[Tuple[Tuple[int, ...], ...], AssignmentTransform]:
        mapped: List[Tuple[int, ...] | None] = [None] * len(self.piece_names)
        for source_piece_index, source_sequence in enumerate(sequences):
            target_piece_index = transform.piece_map[source_piece_index]
            mapped[target_piece_index] = tuple(
                transform.occurrence_map[item] for item in source_sequence
            )
        mapped_sequences = tuple(item for item in mapped if item is not None)
        if len(mapped_sequences) != len(self.piece_names):
            raise RuntimeError("Incomplete transformed assignment")
        if transform.reverse_cycle:
            mapped_sequences = tuple(
                anchored_reverse(sequence) for sequence in mapped_sequences
            )
        return mapped_sequences, transform

    def transform_sequences(
        self,
        sequences: Tuple[Tuple[int, ...], ...],
        transform: AssignmentTransform,
    ) -> Tuple[Tuple[int, ...], ...]:
        mapped, _actual_transform = self.apply_transform(sequences, transform)
        return mapped

    def _assignment_metadata(
        self, sequences: Tuple[Tuple[int, ...], ...]
    ) -> Tuple[Tuple[int, ...], Tuple[int, ...]]:
        signs: List[int] = []
        phases: List[int] = []
        for sequence, base in zip(sequences, self.base_sequences):
            sign, phase = cyclic_orientation_phase(sequence, base)
            signs.append(sign)
            phases.append(phase)
        return tuple(signs), tuple(phases)

    def _sequences_at(self, assignment_id: int) -> Tuple[Tuple[int, ...], ...]:
        total = self.raw_assignment_count()
        if assignment_id < 0 or assignment_id >= total:
            raise IndexError("Assignment index outside the raw domain")
        options = self._piece_options()
        remainder = int(assignment_id)
        if self._required_automorphism is None:
            selected: List[Tuple[int, ...]] = [()] * len(options)
            for piece_index in range(len(options) - 1, -1, -1):
                radix = len(options[piece_index])
                option_index = remainder % radix
                remainder //= radix
                selected[piece_index] = options[piece_index][option_index]
            return tuple(selected)

        representative_options = tuple(
            options[orbit[0]] for orbit in self._equivariance_piece_orbits
        )
        selected_representatives: List[Tuple[int, ...]] = [()] * len(
            representative_options
        )
        for orbit_index in range(len(representative_options) - 1, -1, -1):
            radix = len(representative_options[orbit_index])
            option_index = remainder % radix
            remainder //= radix
            selected_representatives[orbit_index] = representative_options[
                orbit_index
            ][option_index]
        return self._equivariant_sequences_from_choices(selected_representatives)

    def assignment_at(self, assignment_id: int) -> ContourAssignment:
        """Return one raw assignment by mixed-radix index.

        With symmetry enabled, the returned object may be non-canonical. Use
        canonical_assignment_at() in a search pipeline.
        """
        sequences = self._sequences_at(assignment_id)
        transformed = tuple(
            self.apply_transform(sequences, transform) for transform in self.transforms
        )
        canonical_key = min(mapped for mapped, _actual in transformed)
        stabilizer = tuple(
            actual for mapped, actual in transformed if mapped == sequences
        )
        signs, phases = self._assignment_metadata(sequences)
        return ContourAssignment(
            assignment_id=int(assignment_id),
            piece_names=self.piece_names,
            sequences=sequences,
            orientation_signs=signs,
            cyclic_offsets=phases,
            stabilizer=stabilizer,
            canonical_key=canonical_key,
            required_equivariance=self.required_equivariance,
        )

    def canonical_assignment_at(self, assignment_id: int) -> ContourAssignment | None:
        assignment = self.assignment_at(assignment_id)
        if self.symmetry_enabled and assignment.sequences != assignment.canonical_key:
            return None
        return assignment

    def assignment_id_for_sequences(
        self, sequences: Sequence[Sequence[int]]
    ) -> int | None:
        """Return the mixed-radix slot for an exact assignment, if admissible."""

        requested = tuple(tuple(int(item) for item in sequence) for sequence in sequences)
        if len(requested) != len(self.piece_names):
            return None
        options = self._piece_options()
        if self._required_automorphism is None:
            option_indices = []
            for piece_options, sequence in zip(options, requested):
                try:
                    option_indices.append(piece_options.index(sequence))
                except ValueError:
                    return None
            assignment_id = 0
            for option_index, piece_options in zip(option_indices, options):
                assignment_id = assignment_id * len(piece_options) + option_index
            return assignment_id

        representative_options = tuple(
            options[orbit[0]] for orbit in self._equivariance_piece_orbits
        )
        choices = []
        for orbit, piece_options in zip(
            self._equivariance_piece_orbits, representative_options
        ):
            sequence = requested[orbit[0]]
            try:
                choices.append(piece_options.index(sequence))
            except ValueError:
                return None
        selected = tuple(
            piece_options[index]
            for piece_options, index in zip(representative_options, choices)
        )
        if self._equivariant_sequences_from_choices(selected) != requested:
            return None
        assignment_id = 0
        for option_index, piece_options in zip(choices, representative_options):
            assignment_id = assignment_id * len(piece_options) + option_index
        return assignment_id

    def assignment_ids_for_sequence_options(
        self,
        sequence_options: Sequence[Sequence[Sequence[int]]],
    ) -> Tuple[int, ...]:
        """Return raw slots matching independent allowed sequences per piece."""

        if self._required_automorphism is not None:
            raise ValueError(
                "Assignment sequence families are not supported with pointwise "
                "required equivariance"
            )
        if len(sequence_options) != len(self.piece_names):
            raise ValueError("Assignment sequence options must cover every piece")
        enumerator_options = self._piece_options()
        allowed_indices = []
        for piece_options, requested_options in zip(
            enumerator_options, sequence_options
        ):
            requested = {
                tuple(int(item) for item in sequence)
                for sequence in requested_options
            }
            indices = tuple(
                index
                for index, sequence in enumerate(piece_options)
                if sequence in requested
            )
            if not indices:
                return ()
            allowed_indices.append(indices)

        output = []
        for selected_indices in product(*allowed_indices):
            assignment_id = 0
            for option_index, piece_options in zip(
                selected_indices, enumerator_options
            ):
                assignment_id = assignment_id * len(piece_options) + option_index
            output.append(assignment_id)
        return tuple(output)

    def enumerate(self) -> Iterator[ContourAssignment]:
        for assignment_id in range(self.raw_assignment_count()):
            assignment = self.canonical_assignment_at(assignment_id)
            if assignment is not None:
                yield assignment

    def unrestricted_raw_assignment_count(self) -> int:
        count = 1
        for piece_index, base in enumerate(self.base_sequences):
            orientation_count = (
                1
                if piece_index == self.reference_index or not self.allow_reflections
                else 2
            )
            phase_count = (
                1
                if (
                    self.symmetry_enabled
                    and self.mapping_symmetry.complete_mapping_quotient_enabled
                    and piece_index == self.reference_index
                )
                else len(base)
            )
            count *= phase_count * orientation_count
        return count

    def raw_assignment_count(self) -> int:
        if self._required_automorphism is None:
            return self.unrestricted_raw_assignment_count()
        options = self._piece_options()
        count = 1
        for orbit in self._equivariance_piece_orbits:
            count *= len(options[orbit[0]])
        return count

    def transform_for_automorphism(self, name: str) -> AssignmentTransform:
        """Return a certified occurrence/piece transform by declared map name."""

        action = self.mapping_symmetry.action_by_name(str(name))
        return self._assignment_transform(action)

    def required_transform(
        self, assignment: ContourAssignment
    ) -> AssignmentTransform | None:
        if self.required_equivariance is None:
            return None
        action = self.mapping_symmetry.action_by_name(self.required_equivariance)
        transform = self._assignment_transform(action)
        mapped, _ = self.apply_transform(assignment.sequences, transform)
        if mapped != assignment.sequences:
            raise ValueError(
                "Assignment does not satisfy its declared required equivariance"
            )
        if transform.reverse_cycle:
            raise ValueError(
                "Required cyclic equivariance must preserve prototype orientation"
            )
        return transform
