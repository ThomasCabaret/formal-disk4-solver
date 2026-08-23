from __future__ import annotations

from bisect import bisect_right
from dataclasses import dataclass
from itertools import combinations, product
from math import lcm
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


@dataclass(frozen=True)
class _DihedralAssignmentFactor:
    """Lazily index one factor of a dihedral mapping domain.

    For two rotation orbits exchanged by a reflection, compatible source and
    target choices form Cartesian products grouped by a common signature.
    Those products can be enormous, so ``choice_at`` decodes an index without
    ever materializing the combined tuples.
    """

    orbit: Tuple[int, ...]
    single_choices: Tuple[Tuple[Tuple[int, ...], ...], ...] = ()
    paired_groups: Tuple[
        Tuple[
            Tuple[Tuple[Tuple[int, ...], ...], ...],
            Tuple[Tuple[Tuple[int, ...], ...], ...],
        ],
        ...,
    ] = ()
    cumulative_counts: Tuple[int, ...] = ()

    @property
    def choice_count(self) -> int:
        if self.single_choices:
            return len(self.single_choices)
        return self.cumulative_counts[-1] if self.cumulative_counts else 0

    def choice_at(self, index: int) -> Tuple[Tuple[int, ...], ...]:
        position = int(index)
        if position < 0 or position >= self.choice_count:
            raise IndexError("Choice index outside the dihedral factor")
        if self.single_choices:
            return self.single_choices[position]
        group_index = bisect_right(self.cumulative_counts, position)
        previous = (
            0 if group_index == 0 else self.cumulative_counts[group_index - 1]
        )
        source_choices, target_choices = self.paired_groups[group_index]
        local = position - previous
        source_index, target_index = divmod(local, len(target_choices))
        return source_choices[source_index] + target_choices[target_index]


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
        self._cyclic_shift_assignment_domains: Dict[
            str,
            Tuple[
                Tuple[
                    Tuple[int, ...],
                    Tuple[Tuple[Tuple[int, ...], ...], ...],
                ],
                ...,
            ],
        ] = {}
        self._cyclic_dihedral_assignment_domains: Dict[
            Tuple[str, str],
            Tuple[_DihedralAssignmentFactor, ...],
        ] = {}

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

    @staticmethod
    def _permutation_order(permutation: Sequence[int]) -> int:
        """Return the order of a finite permutation."""

        if set(permutation) != set(range(len(permutation))):
            raise ValueError("Cyclic-shift action is not a permutation")
        order = 1
        unseen = set(range(len(permutation)))
        while unseen:
            seed = min(unseen)
            current = seed
            cycle_length = 0
            while current in unseen:
                unseen.remove(current)
                cycle_length += 1
                current = int(permutation[current])
            if current != seed:
                raise ValueError("Cyclic-shift action is not a permutation cycle")
            order = lcm(order, cycle_length)
        return order

    @staticmethod
    def _weak_compositions(total: int, parts: int) -> Iterator[Tuple[int, ...]]:
        """Yield ordered nonnegative ``parts``-tuples summing to ``total``."""

        for dividers in combinations(range(total + parts - 1), parts - 1):
            positions = (-1,) + dividers + (total + parts - 1,)
            yield tuple(
                positions[index + 1] - positions[index] - 1
                for index in range(parts)
            )

    def _cyclic_shift_piece_orbits(
        self, piece_map: Sequence[int], order: int
    ) -> Tuple[Tuple[int, ...], ...]:
        unseen = set(range(len(self.piece_names)))
        output: List[Tuple[int, ...]] = []
        while unseen:
            seed = min(unseen)
            orbit: List[int] = []
            current = seed
            while current not in orbit:
                orbit.append(current)
                unseen.discard(current)
                current = int(piece_map[current])
            if current != seed or len(orbit) not in (1, order):
                raise ValueError(
                    "Cyclic-shift piece orbits must be fixed or have full action order"
                )
            if self.reference_index in orbit:
                offset = orbit.index(self.reference_index)
                orbit = orbit[offset:] + orbit[:offset]
            output.append(tuple(orbit))
        return tuple(output)

    def _build_cyclic_shift_assignment_domain(
        self, automorphism_name: str
    ) -> Tuple[
        Tuple[
            Tuple[int, ...],
            Tuple[Tuple[Tuple[int, ...], ...], ...],
        ],
        ...,
    ]:
        """Factor the mappings compatible with an imposed cyclic shift.

        A rotationally symmetric solution does not permit independent contour
        orientations on every tile.  For a full tile orbit, one representative
        sequence and one weak composition determine every other sequence.  A
        fixed tile is retained only when its contour action advances exactly
        one rotational fundamental domain.  Factoring the domain this way lets
        Graph Lab sample only admissible mappings without enumerating their
        usually astronomical unrestricted complement.
        """

        name = str(automorphism_name)
        cached = self._cyclic_shift_assignment_domains.get(name)
        if cached is not None:
            return cached
        if self._required_automorphism is not None:
            raise ValueError(
                "Cyclic-shift assignment sampling cannot be combined with "
                "pointwise required equivariance"
            )
        transform = self.transform_for_automorphism(name)
        if transform.reverse_cycle:
            raise ValueError("Cyclic-shift equivariance must preserve orientation")
        order = self._permutation_order(transform.occurrence_map)
        if order < 2:
            raise ValueError("Cyclic-shift equivariance needs a nontrivial action")
        for seed in range(len(transform.occurrence_map)):
            current = seed
            orbit = set()
            while current not in orbit:
                orbit.add(current)
                current = transform.occurrence_map[current]
            if current != seed or len(orbit) != order:
                raise ValueError(
                    "Cyclic-shift equivariance requires a free occurrence action"
                )

        piece_options = self._piece_options()
        factors = []
        for orbit in self._cyclic_shift_piece_orbits(transform.piece_map, order):
            lengths = {len(self.base_sequences[index]) for index in orbit}
            if len(lengths) != 1:
                raise ValueError("Cyclic-shift piece orbits need equal contour lengths")
            contour_length = lengths.pop()
            choices: set[Tuple[Tuple[int, ...], ...]] = set()
            if len(orbit) == 1:
                piece_index = orbit[0]
                if contour_length % order:
                    self._cyclic_shift_assignment_domains[name] = ()
                    return ()
                split = contour_length // order
                for sequence in piece_options[piece_index]:
                    mapped = tuple(
                        transform.map_occurrence_id(item) for item in sequence
                    )
                    if mapped == rotate(sequence, split):
                        choices.add((sequence,))
            else:
                for representative in piece_options[orbit[0]]:
                    for prefixes in self._weak_compositions(contour_length, order):
                        split = dict(zip(orbit, prefixes))
                        sequences = {orbit[0]: representative}
                        valid = True
                        for source in orbit[:-1]:
                            target = transform.piece_map[source]
                            mapped = tuple(
                                transform.map_occurrence_id(item)
                                for item in sequences[source]
                            )
                            target_sequence = rotate(mapped, -split[target])
                            if target_sequence not in piece_options[target]:
                                valid = False
                                break
                            sequences[target] = target_sequence
                        if not valid:
                            continue
                        source = orbit[-1]
                        mapped = tuple(
                            transform.map_occurrence_id(item)
                            for item in sequences[source]
                        )
                        if mapped != rotate(representative, split[orbit[0]]):
                            continue
                        choices.add(tuple(sequences[index] for index in orbit))
            if not choices:
                self._cyclic_shift_assignment_domains[name] = ()
                return ()
            factors.append((orbit, tuple(sorted(choices))))
        domain = tuple(factors)
        self._cyclic_shift_assignment_domains[name] = domain
        return domain

    @staticmethod
    def _cyclic_sequence_key(sequence: Sequence[int]) -> Tuple[int, ...]:
        """Canonicalize a finite cyclic sequence without reversing it."""

        normalized = tuple(int(value) for value in sequence)
        if not normalized:
            return ()
        return min(rotate(normalized, offset) for offset in range(len(normalized)))

    def _reflected_choice_signature(
        self,
        orbit: Sequence[int],
        choice: Sequence[Sequence[int]],
        reflection: AssignmentTransform,
    ) -> Tuple[Tuple[int, Tuple[int, ...]], ...]:
        """Map one rotational factor through a graph reflection.

        At mapping level only cyclic incidence order is known.  The common
        reflection-axis phase belongs to the weak cyclic order, so sequences
        are compared modulo their individual cuts here; the downstream
        dihedral weak-order test imposes one common prototype reflection.
        """

        mapped: list[tuple[int, tuple[int, ...]]] = []
        for source_piece, source_sequence in zip(orbit, choice):
            target_piece = int(reflection.piece_map[source_piece])
            target_sequence = tuple(
                reflection.map_occurrence_id(occurrence_id)
                for occurrence_id in source_sequence
            )
            if reflection.reverse_cycle:
                target_sequence = anchored_reverse(target_sequence)
            mapped.append(
                (target_piece, self._cyclic_sequence_key(target_sequence))
            )
        return tuple(sorted(mapped))

    def _choice_signature(
        self,
        orbit: Sequence[int],
        choice: Sequence[Sequence[int]],
    ) -> Tuple[Tuple[int, Tuple[int, ...]], ...]:
        return tuple(
            sorted(
                (
                    int(piece_index),
                    self._cyclic_sequence_key(sequence),
                )
                for piece_index, sequence in zip(orbit, choice)
            )
        )

    def _build_cyclic_dihedral_assignment_domain(
        self,
        rotation_name: str,
        reflection_name: str,
    ) -> Tuple[_DihedralAssignmentFactor, ...]:
        """Factor mappings under rotation and a theorem-forced reflection.

        Rotation factors are first built by the existing exact construction.
        The reflection then either constrains one factor to itself or couples
        two rotation orbits.  Thus two independently exponential choices are
        replaced by one direct product factor.  Cyclic cuts are deliberately
        left free: their single common reflection phase is imposed on the
        completed weak order, where that information actually lives.
        """

        key = (str(rotation_name), str(reflection_name))
        cached = self._cyclic_dihedral_assignment_domains.get(key)
        if cached is not None:
            return cached
        base = self._build_cyclic_shift_assignment_domain(rotation_name)
        if not base:
            self._cyclic_dihedral_assignment_domains[key] = ()
            return ()
        reflection = self.transform_for_automorphism(reflection_name)
        if not reflection.reverse_cycle or self._permutation_order(
            reflection.piece_map
        ) != 2:
            raise ValueError("Dihedral assignment sampling needs a reflection")

        factor_for_piece = {
            piece_index: factor_index
            for factor_index, (orbit, _choices) in enumerate(base)
            for piece_index in orbit
        }
        remaining = set(range(len(base)))
        output = []
        while remaining:
            source_index = min(remaining)
            source_orbit, source_choices = base[source_index]
            target_indices = {
                factor_for_piece[int(reflection.piece_map[piece_index])]
                for piece_index in source_orbit
            }
            if len(target_indices) != 1:
                raise ValueError(
                    "A dihedral reflection must map one rotation orbit to one orbit"
                )
            target_index = target_indices.pop()
            target_orbit, target_choices = base[target_index]
            if target_index == source_index:
                kept = tuple(
                    choice
                    for choice in source_choices
                    if self._reflected_choice_signature(
                        source_orbit, choice, reflection
                    )
                    == self._choice_signature(source_orbit, choice)
                )
                if not kept:
                    self._cyclic_dihedral_assignment_domains[key] = ()
                    return ()
                output.append(
                    _DihedralAssignmentFactor(
                        orbit=tuple(source_orbit),
                        single_choices=kept,
                    )
                )
                remaining.remove(source_index)
                continue

            source_by_signature: Dict[
                Tuple[Tuple[int, Tuple[int, ...]], ...],
                List[Tuple[Tuple[int, ...], ...]],
            ] = {}
            for source_choice in source_choices:
                source_by_signature.setdefault(
                    self._reflected_choice_signature(
                        source_orbit, source_choice, reflection
                    ),
                    [],
                ).append(source_choice)
            target_by_signature: Dict[
                Tuple[Tuple[int, Tuple[int, ...]], ...],
                List[Tuple[Tuple[int, ...], ...]],
            ] = {}
            for target_choice in target_choices:
                target_by_signature.setdefault(
                    self._choice_signature(target_orbit, target_choice), []
                ).append(target_choice)
            combined_orbit = tuple(source_orbit) + tuple(target_orbit)
            common_signatures = sorted(
                set(source_by_signature) & set(target_by_signature)
            )
            paired_groups = tuple(
                (
                    tuple(source_by_signature[signature]),
                    tuple(target_by_signature[signature]),
                )
                for signature in common_signatures
            )
            if not paired_groups:
                self._cyclic_dihedral_assignment_domains[key] = ()
                return ()
            cumulative = []
            count = 0
            for source_group, target_group in paired_groups:
                count += len(source_group) * len(target_group)
                cumulative.append(count)
            output.append(
                _DihedralAssignmentFactor(
                    orbit=combined_orbit,
                    paired_groups=paired_groups,
                    cumulative_counts=tuple(cumulative),
                )
            )
            remaining.remove(source_index)
            remaining.remove(target_index)

        domain = tuple(output)
        self._cyclic_dihedral_assignment_domains[key] = domain
        return domain

    @staticmethod
    def _factored_domain_count(
        domain: Sequence[_DihedralAssignmentFactor],
    ) -> int:
        if not domain:
            return 0
        count = 1
        for factor in domain:
            count *= factor.choice_count
        return count

    def cyclic_dihedral_compatible_assignment_count(
        self,
        rotation_name: str,
        reflection_name: str,
    ) -> int:
        return self._factored_domain_count(
            self._build_cyclic_dihedral_assignment_domain(
                rotation_name, reflection_name
            )
        )

    def cyclic_dihedral_compatible_assignment_at(
        self,
        rotation_name: str,
        reflection_name: str,
        compatible_assignment_id: int,
    ) -> ContourAssignment:
        domain = self._build_cyclic_dihedral_assignment_domain(
            rotation_name, reflection_name
        )
        total = self._factored_domain_count(domain)
        position = int(compatible_assignment_id)
        if position < 0 or position >= total:
            raise IndexError("Assignment index outside the cyclic-dihedral domain")
        selected: List[Tuple[Tuple[int, ...], ...]] = [()] * len(domain)
        for factor_index in range(len(domain) - 1, -1, -1):
            factor = domain[factor_index]
            choice_index = position % factor.choice_count
            position //= factor.choice_count
            selected[factor_index] = factor.choice_at(choice_index)
        sequences: List[Tuple[int, ...] | None] = [None] * len(self.piece_names)
        for factor, factor_sequences in zip(domain, selected):
            for piece_index, sequence in zip(factor.orbit, factor_sequences):
                sequences[piece_index] = sequence
        complete = tuple(sequence for sequence in sequences if sequence is not None)
        if len(complete) != len(self.piece_names):
            raise RuntimeError("Incomplete cyclic-dihedral assignment")
        raw_assignment_id = self.assignment_id_for_sequences(complete)
        if raw_assignment_id is None:
            raise RuntimeError("Dihedral assignment is absent from the raw domain")
        return self.assignment_at(raw_assignment_id)

    def cyclic_shift_compatible_assignment_count(
        self, automorphism_name: str
    ) -> int:
        """Return the exact number of mappings compatible with a cyclic action."""

        domain = self._build_cyclic_shift_assignment_domain(automorphism_name)
        if not domain:
            return 0
        count = 1
        for _orbit, choices in domain:
            count *= len(choices)
        return count

    def cyclic_shift_compatible_assignment_at(
        self, automorphism_name: str, compatible_assignment_id: int
    ) -> ContourAssignment:
        """Decode one mixed-radix slot of the compatible mapping domain."""

        domain = self._build_cyclic_shift_assignment_domain(automorphism_name)
        total = self.cyclic_shift_compatible_assignment_count(automorphism_name)
        position = int(compatible_assignment_id)
        if position < 0 or position >= total:
            raise IndexError("Assignment index outside the cyclic-shift domain")
        selected: List[Tuple[Tuple[int, ...], ...]] = [()] * len(domain)
        for factor_index in range(len(domain) - 1, -1, -1):
            choices = domain[factor_index][1]
            choice_index = position % len(choices)
            position //= len(choices)
            selected[factor_index] = choices[choice_index]
        sequences: List[Tuple[int, ...] | None] = [None] * len(self.piece_names)
        for (orbit, _choices), orbit_sequences in zip(domain, selected):
            for piece_index, sequence in zip(orbit, orbit_sequences):
                sequences[piece_index] = sequence
        complete = tuple(sequence for sequence in sequences if sequence is not None)
        if len(complete) != len(self.piece_names):
            raise RuntimeError("Incomplete cyclic-shift-compatible assignment")
        raw_assignment_id = self.assignment_id_for_sequences(complete)
        if raw_assignment_id is None:
            raise RuntimeError("Compatible assignment is absent from the raw domain")
        return self.assignment_at(raw_assignment_id)

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
