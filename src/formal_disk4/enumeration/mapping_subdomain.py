from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping, Sequence, TYPE_CHECKING, Tuple

from formal_disk4.maps.base import PlanarMap

if TYPE_CHECKING:
    from .assignments import AssignmentEnumerator, ContourAssignment


@dataclass(frozen=True)
class MappingSubdomain:
    """A deterministic, imposed shard of the mapping domain.

    This is deliberately separate from the intrinsic-symmetry quotient.  The
    assignment and cyclic-shift split select one shard, while ``strict_order``
    is enforced incrementally during weak-order enumeration.
    """

    shard_id: str
    map_name: str
    assignment_sequences: Tuple[Tuple[int, ...], ...]
    cyclic_shift_split: Tuple[int, ...]
    strict_order: Tuple[int, ...]
    fundamental_blocks: Tuple[Tuple[int, ...], ...]
    occurrence_names: Tuple[str, ...]
    piece_names: Tuple[str, ...]

    @classmethod
    def from_config(
        cls,
        planar_map: PlanarMap,
        occurrence_names: Sequence[str],
        raw: Mapping[str, Any] | None,
    ) -> "MappingSubdomain | None":
        if not isinstance(raw, Mapping) or not bool(raw.get("enabled", False)):
            return None
        shard_id = str(raw.get("id", "")).strip()
        if not shard_id:
            raise ValueError("mapping_subdomain.id must be non-empty")
        configured_map = str(raw.get("map", planar_map.name))
        if configured_map != planar_map.name:
            raise ValueError(
                f"Mapping shard {shard_id!r} targets {configured_map!r}, not "
                f"{planar_map.name!r}"
            )

        names = tuple(str(name) for name in occurrence_names)
        occurrence_index = {name: index for index, name in enumerate(names)}
        piece_names = tuple(piece.name for piece in planar_map.pieces)
        sequences_raw = raw.get("assignment_sequences")
        if not isinstance(sequences_raw, Mapping):
            raise ValueError("mapping_subdomain.assignment_sequences must be an object")
        if set(str(key) for key in sequences_raw) != set(piece_names):
            raise ValueError(
                "mapping_subdomain.assignment_sequences must specify every map piece"
            )

        assignment_sequences = []
        for piece in planar_map.pieces:
            sequence_raw = sequences_raw[piece.name]
            if not isinstance(sequence_raw, Sequence) or isinstance(
                sequence_raw, (str, bytes)
            ):
                raise ValueError(
                    f"Mapping shard sequence for {piece.name!r} must be a list"
                )
            try:
                sequence = tuple(occurrence_index[str(name)] for name in sequence_raw)
            except KeyError as error:
                raise ValueError(
                    f"Unknown occurrence in mapping shard {shard_id!r}: {error.args[0]}"
                ) from error
            expected = {
                occurrence_index[f"{piece.name}:{vertex}"]
                for vertex in piece.contour_vertices
            }
            if len(sequence) != len(expected) or set(sequence) != expected:
                raise ValueError(
                    f"Mapping shard sequence for {piece.name!r} is not its contour"
                )
            assignment_sequences.append(sequence)

        split_raw = raw.get("cyclic_shift_split")
        if not isinstance(split_raw, Mapping) or set(str(key) for key in split_raw) != set(
            piece_names
        ):
            raise ValueError(
                "mapping_subdomain.cyclic_shift_split must specify every map piece"
            )
        split = tuple(int(split_raw[piece]) for piece in piece_names)
        if any(
            value < 0 or value > len(sequence)
            for value, sequence in zip(split, assignment_sequences)
        ):
            raise ValueError("mapping_subdomain.cyclic_shift_split is out of range")

        order_raw = raw.get("fundamental_strict_order")
        if not isinstance(order_raw, Sequence) or isinstance(order_raw, (str, bytes)):
            raise ValueError(
                "mapping_subdomain.fundamental_strict_order must be a list"
            )
        try:
            strict_order = tuple(occurrence_index[str(name)] for name in order_raw)
        except KeyError as error:
            raise ValueError(
                f"Unknown occurrence in mapping shard order: {error.args[0]}"
            ) from error
        if len(set(strict_order)) != len(strict_order):
            raise ValueError("mapping_subdomain.fundamental_strict_order has duplicates")

        prefix_occurrences = {
            occurrence_id
            for sequence, length in zip(assignment_sequences, split)
            for occurrence_id in sequence[:length]
        }
        if not set(strict_order).issubset(prefix_occurrences):
            missing = [
                names[item] for item in strict_order if item not in prefix_occurrences
            ]
            raise ValueError(
                "Mapping shard strict order contains occurrences outside its "
                f"fundamental domain: {missing}"
            )

        blocks_raw = raw.get("fundamental_blocks", ())
        if not isinstance(blocks_raw, Sequence) or isinstance(
            blocks_raw, (str, bytes)
        ):
            raise ValueError("mapping_subdomain.fundamental_blocks must be a list")
        fundamental_blocks = []
        for block_raw in blocks_raw:
            if not isinstance(block_raw, Sequence) or isinstance(
                block_raw, (str, bytes)
            ):
                raise ValueError("Each mapping shard fundamental block must be a list")
            try:
                block = tuple(
                    sorted(occurrence_index[str(name)] for name in block_raw)
                )
            except KeyError as error:
                raise ValueError(
                    f"Unknown occurrence in mapping shard block: {error.args[0]}"
                ) from error
            if not block:
                raise ValueError("Mapping shard fundamental blocks cannot be empty")
            fundamental_blocks.append(block)
        if fundamental_blocks:
            flattened_blocks = tuple(
                item for block in fundamental_blocks for item in block
            )
            if (
                len(flattened_blocks) != len(prefix_occurrences)
                or len(set(flattened_blocks)) != len(flattened_blocks)
                or set(flattened_blocks) != prefix_occurrences
            ):
                raise ValueError(
                    "mapping_subdomain.fundamental_blocks must partition the "
                    "selected cyclic-shift prefix"
                )

        return cls(
            shard_id=shard_id,
            map_name=planar_map.name,
            assignment_sequences=tuple(assignment_sequences),
            cyclic_shift_split=split,
            strict_order=strict_order,
            fundamental_blocks=tuple(fundamental_blocks),
            occurrence_names=names,
            piece_names=piece_names,
        )

    def assignment_ids(self, enumerator: "AssignmentEnumerator") -> Tuple[int, ...]:
        assignment_id = enumerator.assignment_id_for_sequences(
            self.assignment_sequences
        )
        if assignment_id is None:
            raise ValueError(
                f"Mapping shard {self.shard_id!r} selects an invalid contour assignment"
            )
        return (assignment_id,)

    def allows_assignment(self, assignment: "ContourAssignment") -> bool:
        return assignment.sequences == self.assignment_sequences

    def allows_cyclic_shift_split(self, split: Sequence[int]) -> bool:
        return tuple(int(value) for value in split) == self.cyclic_shift_split

    def allows_next_block(
        self,
        counters: Sequence[int],
        mask: int,
        sequences: Sequence[Sequence[int]],
    ) -> bool:
        """Check a candidate block against the shard order using only prefixes."""

        placed = {
            occurrence_id
            for sequence, counter in zip(sequences, counters)
            for occurrence_id in sequence[: int(counter)]
        }
        next_occurrences = {
            sequence[int(counters[piece_index])]
            for piece_index, sequence in enumerate(sequences)
            if mask & (1 << piece_index)
        }
        if self.fundamental_blocks:
            completed_block_count = 0
            for block in self.fundamental_blocks:
                if set(block).issubset(placed):
                    completed_block_count += 1
                else:
                    break
            if completed_block_count >= len(self.fundamental_blocks):
                return False
            if next_occurrences != set(
                self.fundamental_blocks[completed_block_count]
            ):
                return False
        order_index = {
            occurrence_id: index
            for index, occurrence_id in enumerate(self.strict_order)
        }
        ordered_next = [
            order_index[occurrence_id]
            for occurrence_id in next_occurrences
            if occurrence_id in order_index
        ]
        # Strict means that two selected landmarks cannot occupy one weak-order
        # block.  Before landmark j is placed, every earlier landmark must be.
        if len(ordered_next) > 1:
            return False
        if ordered_next:
            index = ordered_next[0]
            if any(item not in placed for item in self.strict_order[:index]):
                return False
        return True

    def allows_leaf(self, blocks: Sequence[Sequence[int]]) -> bool:
        if self.fundamental_blocks:
            prefix = tuple(
                tuple(sorted(int(item) for item in block))
                for block in blocks[: len(self.fundamental_blocks)]
            )
            if prefix != self.fundamental_blocks:
                return False
        positions: dict[int, int] = {}
        for block_index, block in enumerate(blocks):
            for occurrence_id in block:
                positions[int(occurrence_id)] = block_index
        try:
            ordered_positions = tuple(positions[item] for item in self.strict_order)
        except KeyError:
            return False
        return all(
            left < right
            for left, right in zip(ordered_positions, ordered_positions[1:])
        )

    def to_dict(self) -> dict[str, object]:
        return {
            "id": self.shard_id,
            "map": self.map_name,
            "assignment_sequences": {
                piece_name: [
                    self.occurrence_names[item] for item in sequence
                ]
                for piece_name, sequence in zip(
                    self.piece_names, self.assignment_sequences
                )
            },
            "cyclic_shift_split": list(self.cyclic_shift_split),
            "fundamental_strict_order": [
                self.occurrence_names[item] for item in self.strict_order
            ],
            "fundamental_blocks": [
                [self.occurrence_names[item] for item in block]
                for block in self.fundamental_blocks
            ],
        }
