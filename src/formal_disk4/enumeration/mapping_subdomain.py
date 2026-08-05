from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
from typing import Any, Mapping, Sequence, TYPE_CHECKING, Tuple

from formal_disk4.maps.base import PlanarMap

if TYPE_CHECKING:
    from .assignments import AssignmentEnumerator, ContourAssignment


@dataclass(frozen=True)
class MappingSubdomain:
    """A deterministic, imposed shard of the mapping domain.

    SEARCH-DOMAIN RESTRICTION: rejecting a mapping here is an imposed experiment
    shard, not a proof that the unrestricted structural case is impossible.

    This is deliberately separate from the intrinsic-symmetry quotient.  The
    assignment and cyclic-shift split select one shard, while ``strict_order``
    is enforced incrementally during weak-order enumeration.
    """

    shard_id: str
    map_name: str
    assignment_sequences: Tuple[Tuple[int, ...], ...]
    assignment_sequence_options: Tuple[Tuple[Tuple[int, ...], ...], ...]
    cyclic_shift_split: Tuple[int, ...] | None
    strict_order: Tuple[int, ...]
    full_strict_order: Tuple[int, ...]
    fundamental_blocks: Tuple[Tuple[int, ...], ...]
    occurrence_names: Tuple[str, ...]
    piece_names: Tuple[str, ...]
    cyclic_occurrence_map: Tuple[int, ...]
    cyclic_occurrence_inverse: Tuple[int, ...]
    cyclic_action_order: int

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
        def parse_sequence(piece_name: str, sequence_raw: object) -> Tuple[int, ...]:
            if not isinstance(sequence_raw, Sequence) or isinstance(
                sequence_raw, (str, bytes)
            ):
                raise ValueError(
                    f"Mapping shard sequence for {piece_name!r} must be a list"
                )
            try:
                sequence = tuple(occurrence_index[str(name)] for name in sequence_raw)
            except KeyError as error:
                raise ValueError(
                    f"Unknown occurrence in mapping shard {shard_id!r}: {error.args[0]}"
                ) from error
            piece = next(item for item in planar_map.pieces if item.name == piece_name)
            expected = {occurrence_index[f"{piece.name}:{vertex}"] for vertex in piece.contour_vertices}
            if len(sequence) != len(expected) or set(sequence) != expected:
                raise ValueError(
                    f"Mapping shard sequence for {piece.name!r} is not its contour"
                )
            return sequence

        sequences_raw = raw.get("assignment_sequences")
        family_raw = raw.get("assignment_family")
        if isinstance(sequences_raw, Mapping) and isinstance(family_raw, Mapping):
            raise ValueError(
                "Use assignment_sequences or assignment_family, not both"
            )
        assignment_sequence_options = []
        if isinstance(sequences_raw, Mapping):
            if set(str(key) for key in sequences_raw) != set(piece_names):
                raise ValueError(
                    "mapping_subdomain.assignment_sequences must specify every map piece"
                )
            assignment_sequence_options = [
                (parse_sequence(piece.name, sequences_raw[piece.name]),)
                for piece in planar_map.pieces
            ]
        elif isinstance(family_raw, Mapping):
            fixed_raw = family_raw.get("fixed_sequences", {})
            signs_raw = family_raw.get("orientation_signs", {})
            if not isinstance(fixed_raw, Mapping) or not isinstance(signs_raw, Mapping):
                raise ValueError(
                    "assignment_family fixed_sequences and orientation_signs "
                    "must be objects"
                )
            for piece in planar_map.pieces:
                if piece.name in fixed_raw:
                    assignment_sequence_options.append(
                        (parse_sequence(piece.name, fixed_raw[piece.name]),)
                    )
                    continue
                if piece.name not in signs_raw:
                    raise ValueError(
                        f"assignment_family has no rule for piece {piece.name!r}"
                    )
                sign = int(signs_raw[piece.name])
                if sign not in (-1, 1):
                    raise ValueError("assignment_family orientations must be +/-1")
                base = tuple(
                    occurrence_index[f"{piece.name}:{vertex}"]
                    for vertex in piece.contour_vertices
                )
                oriented = base if sign == 1 else tuple(reversed(base))
                assignment_sequence_options.append(
                    tuple(
                        oriented[phase:] + oriented[:phase]
                        for phase in range(len(oriented))
                    )
                )
        else:
            raise ValueError(
                "mapping_subdomain requires assignment_sequences or assignment_family"
            )
        assignment_sequences = tuple(options[0] for options in assignment_sequence_options)

        split_raw = raw.get("cyclic_shift_split")
        if split_raw == "all_compatible":
            split = None
        elif isinstance(split_raw, Mapping) and set(
            str(key) for key in split_raw
        ) == set(piece_names):
            split = tuple(int(split_raw[piece]) for piece in piece_names)
        else:
            raise ValueError(
                "mapping_subdomain.cyclic_shift_split must specify every map "
                "piece or be 'all_compatible'"
            )
        if split is not None and any(
            value < 0 or value > len(options[0])
            for value, options in zip(split, assignment_sequence_options)
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

        full_order_raw = raw.get("full_strict_order", ())
        if not isinstance(full_order_raw, Sequence) or isinstance(
            full_order_raw, (str, bytes)
        ):
            raise ValueError("mapping_subdomain.full_strict_order must be a list")
        try:
            full_strict_order = tuple(
                occurrence_index[str(name)] for name in full_order_raw
            )
        except KeyError as error:
            raise ValueError(
                f"Unknown occurrence in full mapping shard order: {error.args[0]}"
            ) from error
        if len(set(full_strict_order)) != len(full_strict_order):
            raise ValueError("mapping_subdomain.full_strict_order has duplicates")

        prefix_occurrences = set()
        if split is not None:
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
        if fundamental_blocks and split is None:
            raise ValueError(
                "Exact fundamental_blocks require an exact cyclic_shift_split"
            )
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

        automorphism_name = str(raw.get("cyclic_shift_automorphism", "")).strip()
        if not automorphism_name:
            if full_strict_order:
                raise ValueError(
                    "full_strict_order requires cyclic_shift_automorphism"
                )
            occurrence_map = tuple(range(len(names)))
        else:
            automorphism = next(
                (
                    item
                    for item in planar_map.automorphisms
                    if item.name == automorphism_name
                ),
                None,
            )
            if automorphism is None:
                raise ValueError(
                    f"Unknown cyclic shift automorphism {automorphism_name!r}"
                )
            occurrences = planar_map.occurrences()
            by_occurrence = {
                occurrence: index for index, occurrence in enumerate(occurrences)
            }
            occurrence_map = tuple(
                by_occurrence[automorphism.map_occurrence(occurrence)]
                for occurrence in occurrences
            )
        inverse = [0] * len(occurrence_map)
        for source, target in enumerate(occurrence_map):
            inverse[target] = source
        action_order = 1
        current = tuple(range(len(occurrence_map)))
        while True:
            current = tuple(occurrence_map[item] for item in current)
            if current == tuple(range(len(occurrence_map))):
                break
            action_order += 1
            if action_order > len(occurrence_map):
                raise ValueError("Cyclic shift occurrence action has invalid order")

        return cls(
            shard_id=shard_id,
            map_name=planar_map.name,
            assignment_sequences=assignment_sequences,
            assignment_sequence_options=tuple(assignment_sequence_options),
            cyclic_shift_split=split,
            strict_order=strict_order,
            full_strict_order=full_strict_order,
            fundamental_blocks=tuple(fundamental_blocks),
            occurrence_names=names,
            piece_names=piece_names,
            cyclic_occurrence_map=occurrence_map,
            cyclic_occurrence_inverse=tuple(inverse),
            cyclic_action_order=action_order,
        )

    def assignment_ids(self, enumerator: "AssignmentEnumerator") -> Tuple[int, ...]:
        assignment_ids = enumerator.assignment_ids_for_sequence_options(
            self.assignment_sequence_options
        )
        if not assignment_ids:
            raise ValueError(
                f"Mapping shard {self.shard_id!r} selects no contour assignment"
            )
        return assignment_ids

    def allows_assignment(self, assignment: "ContourAssignment") -> bool:
        return all(
            sequence in options
            for sequence, options in zip(
                assignment.sequences, self.assignment_sequence_options
            )
        )

    def allows_cyclic_shift_split(
        self,
        split: Sequence[int],
        sequences: Sequence[Sequence[int]],
    ) -> bool:
        split_tuple = tuple(int(value) for value in split)
        if (
            self.cyclic_shift_split is not None
            and split_tuple != self.cyclic_shift_split
        ):
            return False
        if self.strict_order:
            prefix = {
                item
                for sequence, length in zip(sequences, split_tuple)
                for item in sequence[:length]
            }
            if not set(self.strict_order).issubset(prefix):
                return False
        return self._fundamental_chains(split_tuple, tuple(map(tuple, sequences))) is not None

    @lru_cache(maxsize=None)
    def _fundamental_chains(
        self,
        split: Tuple[int, ...],
        sequences: Tuple[Tuple[int, ...], ...],
    ) -> Tuple[Tuple[int, ...], ...] | None:
        if not self.full_strict_order:
            return ()
        fundamental = {
            item
            for sequence, length in zip(sequences, split)
            for item in sequence[:length]
        }
        domains = []
        current = set(fundamental)
        for _ in range(self.cyclic_action_order):
            domains.append(current)
            current = {self.cyclic_occurrence_map[item] for item in current}
        tagged = []
        for occurrence_id in self.full_strict_order:
            memberships = [
                index for index, domain in enumerate(domains) if occurrence_id in domain
            ]
            if len(memberships) != 1:
                return None
            domain_index = memberships[0]
            preimage = occurrence_id
            for _ in range(domain_index):
                preimage = self.cyclic_occurrence_inverse[preimage]
            tagged.append((domain_index, preimage))
        if any(
            left[0] > right[0] for left, right in zip(tagged, tagged[1:])
        ):
            return None
        chains = []
        for domain_index in range(self.cyclic_action_order):
            chain = tuple(
                preimage for index, preimage in tagged if index == domain_index
            )
            if len(chain) > 1:
                chains.append(chain)
        return tuple(chains)

    def allows_next_block(
        self,
        counters: Sequence[int],
        mask: int,
        sequences: Sequence[Sequence[int]],
        cyclic_shift_split: Sequence[int] | None = None,
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
        if cyclic_shift_split is not None and self.full_strict_order:
            chains = self._fundamental_chains(
                tuple(int(value) for value in cyclic_shift_split),
                tuple(tuple(sequence) for sequence in sequences),
            )
            if chains is None:
                return False
            for chain in chains:
                for before, after in zip(chain, chain[1:]):
                    if after in next_occurrences and before not in placed:
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
        if not all(
            left < right
            for left, right in zip(ordered_positions, ordered_positions[1:])
        ):
            return False
        try:
            full_positions = tuple(
                positions[item] for item in self.full_strict_order
            )
        except KeyError:
            return False
        return all(
            left < right
            for left, right in zip(full_positions, full_positions[1:])
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
            "assignment_option_counts": dict(
                zip(
                    self.piece_names,
                    (len(options) for options in self.assignment_sequence_options),
                )
            ),
            "cyclic_shift_split": (
                list(self.cyclic_shift_split)
                if self.cyclic_shift_split is not None
                else "all_compatible"
            ),
            "fundamental_strict_order": [
                self.occurrence_names[item] for item in self.strict_order
            ],
            "full_strict_order": [
                self.occurrence_names[item] for item in self.full_strict_order
            ],
            "fundamental_blocks": [
                [self.occurrence_names[item] for item in block]
                for block in self.fundamental_blocks
            ],
        }
