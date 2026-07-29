from __future__ import annotations

from dataclasses import dataclass
from itertools import product
from typing import Dict, Iterable, Iterator, List, Mapping, Sequence, Tuple

from formal_disk4.maps.base import MapAutomorphism, Occurrence, PlanarMap


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
        }


class AssignmentEnumerator:
    """Enumerate phase/orientation assignments, optionally quotienting map symmetry."""

    def __init__(
        self,
        planar_map: PlanarMap,
        allow_reflections: bool = True,
        symmetry_mode: str = "incremental",
    ) -> None:
        if symmetry_mode not in {"off", "assignment", "incremental"}:
            raise ValueError("symmetry_mode must be off, assignment, or incremental")
        self.planar_map = planar_map
        self.allow_reflections = allow_reflections
        self.symmetry_mode = symmetry_mode
        self.piece_names = tuple(piece.name for piece in planar_map.pieces)
        self.piece_index = {name: index for index, name in enumerate(self.piece_names)}
        self.occurrences = planar_map.occurrences()
        self.occurrence_index = {occurrence: index for index, occurrence in enumerate(self.occurrences)}
        self.occurrence_names = tuple(occurrence.name for occurrence in self.occurrences)
        self.base_sequences = tuple(
            tuple(
                self.occurrence_index[Occurrence(piece.name, vertex)]
                for vertex in piece.contour_vertices
            )
            for piece in planar_map.pieces
        )
        self.reference_index = self.piece_index[planar_map.reference_piece]
        self.transforms = self._build_normalized_transforms()

    def _piece_options(self) -> Tuple[Tuple[Tuple[int, ...], ...], ...]:
        options: List[Tuple[Tuple[int, ...], ...]] = []
        for piece_index, base in enumerate(self.base_sequences):
            piece_options: List[Tuple[int, ...]] = []
            signs = (1,) if piece_index == self.reference_index or not self.allow_reflections else (1, -1)
            for sign in signs:
                oriented = base if sign == 1 else tuple(reversed(base))
                for phase in range(len(base)):
                    piece_options.append(tuple(oriented[phase:] + oriented[:phase]))
            options.append(tuple(piece_options))
        return tuple(options)

    def _raw_sequences(self) -> Iterator[Tuple[Tuple[int, ...], ...]]:
        yield from product(*self._piece_options())

    def _map_sequences(
        self,
        sequences: Tuple[Tuple[int, ...], ...],
        automorphism: MapAutomorphism,
    ) -> Tuple[Tuple[Tuple[int, ...], ...], bool, Tuple[int, ...]]:
        mapped: List[Tuple[int, ...] | None] = [None] * len(self.piece_names)
        occurrence_map = [0] * len(self.occurrences)
        for source_id, occurrence in enumerate(self.occurrences):
            target = automorphism.map_occurrence(occurrence)
            occurrence_map[source_id] = self.occurrence_index[target]

        for source_piece_index, source_sequence in enumerate(sequences):
            source_piece = self.piece_names[source_piece_index]
            target_piece = automorphism.map_piece(source_piece)
            target_piece_index = self.piece_index[target_piece]
            mapped[target_piece_index] = tuple(occurrence_map[item] for item in source_sequence)

        mapped_sequences = tuple(item for item in mapped if item is not None)
        if len(mapped_sequences) != len(self.piece_names):
            raise RuntimeError("Incomplete transformed assignment")

        central_sequence = mapped_sequences[self.reference_index]
        central_base = self.base_sequences[self.reference_index]
        central_sign, _ = cyclic_orientation_phase(central_sequence, central_base)
        reverse_cycle = central_sign == -1
        if reverse_cycle:
            mapped_sequences = tuple(anchored_reverse(sequence) for sequence in mapped_sequences)

        return mapped_sequences, reverse_cycle, tuple(occurrence_map)

    def _build_normalized_transforms(self) -> Tuple[AssignmentTransform, ...]:
        # The occurrence permutation is map-level data.  The optional reversal needed
        # to restore the orientation of the reference contour can depend on the current
        # assignment when an automorphism moves the reference piece to another copy.
        transforms: List[AssignmentTransform] = []
        for automorphism in self.planar_map.automorphisms:
            occurrence_map = tuple(
                self.occurrence_index[automorphism.map_occurrence(occurrence)]
                for occurrence in self.occurrences
            )
            transforms.append(
                AssignmentTransform(
                    automorphism_name=automorphism.name,
                    occurrence_map=occurrence_map,
                    reverse_cycle=False,
                )
            )
        return tuple(transforms)

    def apply_transform(
        self,
        sequences: Tuple[Tuple[int, ...], ...],
        transform: AssignmentTransform,
    ) -> Tuple[Tuple[Tuple[int, ...], ...], AssignmentTransform]:
        automorphism = next(
            item
            for item in self.planar_map.automorphisms
            if item.name == transform.automorphism_name
        )
        mapped, reverse_cycle, occurrence_map = self._map_sequences(sequences, automorphism)
        return mapped, AssignmentTransform(
            automorphism_name=transform.automorphism_name,
            occurrence_map=occurrence_map,
            reverse_cycle=reverse_cycle,
        )

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

    def enumerate(self) -> Iterator[ContourAssignment]:
        emitted_keys: set[Tuple[Tuple[int, ...], ...]] = set()
        assignment_id = 0
        for sequences in self._raw_sequences():
            key = tuple(sequences)
            transformed = tuple(
                self.apply_transform(sequences, transform) for transform in self.transforms
            )
            if self.symmetry_mode != "off":
                canonical_key = min(mapped for mapped, _actual in transformed)
                if key != canonical_key:
                    continue
            else:
                canonical_key = key

            if canonical_key in emitted_keys:
                continue
            emitted_keys.add(canonical_key)

            stabilizer = tuple(
                actual
                for mapped, actual in transformed
                if mapped == sequences
            )
            signs, phases = self._assignment_metadata(sequences)
            yield ContourAssignment(
                assignment_id=assignment_id,
                piece_names=self.piece_names,
                sequences=sequences,
                orientation_signs=signs,
                cyclic_offsets=phases,
                stabilizer=stabilizer,
                canonical_key=canonical_key,
            )
            assignment_id += 1


    def assignment_at(self, assignment_id: int) -> ContourAssignment:
        """Return one raw assignment without scanning previous assignments.

        This random-access path is intentionally restricted to symmetry_mode=off.
        Large map families can then checkpoint an assignment index without first
        materializing or replaying a multi-billion-element Cartesian product.
        """

        if self.symmetry_mode != "off":
            raise ValueError("assignment_at requires symmetry_mode='off'")
        total = self.raw_assignment_count()
        if assignment_id < 0 or assignment_id >= total:
            raise IndexError("Assignment index outside the raw domain")

        options = self._piece_options()
        remainder = int(assignment_id)
        selected: List[Tuple[int, ...]] = [()] * len(options)
        for piece_index in range(len(options) - 1, -1, -1):
            radix = len(options[piece_index])
            option_index = remainder % radix
            remainder //= radix
            selected[piece_index] = options[piece_index][option_index]
        sequences = tuple(selected)

        transformed = tuple(
            self.apply_transform(sequences, transform) for transform in self.transforms
        )
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
            canonical_key=sequences,
        )

    def raw_assignment_count(self) -> int:
        count = 1
        for piece_index, base in enumerate(self.base_sequences):
            orientation_count = 1 if piece_index == self.reference_index or not self.allow_reflections else 2
            count *= len(base) * orientation_count
        return count
