from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, Iterable, Mapping, Sequence, Tuple

from formal_disk4.maps.base import MapAutomorphism, Occurrence, PlanarMap


Block = Tuple[int, ...]
Blocks = Tuple[Block, ...]


@dataclass(frozen=True)
class SymmetryAction:
    """One certified automorphism of the complete combinatorial map."""

    name: str
    piece_permutation: Tuple[int, ...]
    vertex_permutation: Tuple[int, ...]
    occurrence_permutation: Tuple[int, ...]
    orientation_sign: int

    @property
    def key(self) -> Tuple[Tuple[int, ...], Tuple[int, ...]]:
        return self.piece_permutation, self.vertex_permutation

    def compose(self, other: "SymmetryAction", *, name: str) -> "SymmetryAction":
        """Return self after other."""
        return SymmetryAction(
            name=name,
            piece_permutation=tuple(
                self.piece_permutation[index] for index in other.piece_permutation
            ),
            vertex_permutation=tuple(
                self.vertex_permutation[index] for index in other.vertex_permutation
            ),
            occurrence_permutation=tuple(
                self.occurrence_permutation[index]
                for index in other.occurrence_permutation
            ),
            orientation_sign=self.orientation_sign * other.orientation_sign,
        )

    def commutes_with(self, other: "SymmetryAction") -> bool:
        return all(
            self.piece_permutation[other.piece_permutation[index]]
            == other.piece_permutation[self.piece_permutation[index]]
            for index in range(len(self.piece_permutation))
        ) and all(
            self.vertex_permutation[other.vertex_permutation[index]]
            == other.vertex_permutation[self.vertex_permutation[index]]
            for index in range(len(self.vertex_permutation))
        )


class MappingSymmetryQuotient:
    """Canonical quotient of complete offset mappings under intrinsic symmetry.

    QUOTIENT JUSTIFICATION: every action is a certified bijective automorphism
    of the complete combinatorial map. Keeping the lexicographically canonical
    orbit representative therefore removes only equivalent mappings, never an
    inequivalent solution.

    The quotient acts on the complete weak cyclic order.  Each image is returned
    to the search gauge by orienting the reference copy directly and rotating the
    cyclic order so the first base occurrence of the reference copy lies in block
    zero.  This handles automorphisms that move the reference piece without
    confusing an imposed equivariance assumption with an intrinsic quotient.
    """

    def __init__(
        self,
        planar_map: PlanarMap,
        *,
        required_equivariance: str | None = None,
        required_equivariance_on_weak_orders: bool = True,
    ) -> None:
        self.planar_map = planar_map
        self.complete_mapping_quotient_enabled = (
            required_equivariance is None
            or bool(required_equivariance_on_weak_orders)
        )
        self.piece_names = tuple(piece.name for piece in planar_map.pieces)
        self.vertex_names = tuple(vertex.name for vertex in planar_map.vertices)
        self.piece_index = {name: index for index, name in enumerate(self.piece_names)}
        self.vertex_index = {name: index for index, name in enumerate(self.vertex_names)}
        self.occurrences = planar_map.occurrences()
        self.occurrence_index = {
            occurrence: index for index, occurrence in enumerate(self.occurrences)
        }
        self.occurrence_piece_index = tuple(
            self.piece_index[occurrence.piece] for occurrence in self.occurrences
        )
        self.reference_piece_index = self.piece_index[planar_map.reference_piece]
        reference_piece = planar_map.piece_map()[planar_map.reference_piece]
        self.reference_sequence = tuple(
            self.occurrence_index[Occurrence(planar_map.reference_piece, vertex)]
            for vertex in reference_piece.contour_vertices
        )
        self.reference_anchor = self.reference_sequence[0]

        declared = tuple(
            self._certify_automorphism(automorphism)
            for automorphism in planar_map.automorphisms
        )
        self.group = self._group_closure(declared)
        self._declared_by_name = {
            action.name: action for action in declared
        }
        if len(self._declared_by_name) != len(declared):
            raise ValueError(f"Duplicate automorphism name on map {planar_map.name}")

        required_action = None
        if required_equivariance is not None:
            required_action = self._declared_by_name.get(required_equivariance)
            if required_action is None:
                raise ValueError(
                    f"Unknown or uncertified required equivariance "
                    f"{required_equivariance!r} for map {planar_map.name!r}"
                )
        self.required_action = required_action
        self.quotient_group = tuple(
            action
            for action in self.group
            if required_action is None or action.commutes_with(required_action)
        )
        if not self.quotient_group:
            raise RuntimeError("The intrinsic quotient group lost its identity")
        self.mapping_actions = self._effective_mapping_actions(
            required_action,
            required_equivariance_on_weak_orders=bool(
                required_equivariance_on_weak_orders
            ),
        )

        # These actions preserve both the assignment-level anchor and its cyclic
        # orientation.  An orientation-reversing action cannot be applied safely
        # to the independently cut contour sequences: the complete weak order is
        # needed to recover the common cut after reflection.  Such actions remain
        # available to the complete-mapping quotient below.
        self.assignment_group = tuple(
            action
            for action in self.quotient_group
            if action.piece_permutation[self.reference_piece_index]
            == self.reference_piece_index
            and action.occurrence_permutation[self.reference_anchor]
            == self.reference_anchor
            and action.orientation_sign == 1
        )
        if not self.assignment_group:
            raise RuntimeError("The assignment quotient group lost its identity")

    def _certify_automorphism(self, automorphism: MapAutomorphism) -> SymmetryAction:
        piece_map = dict(automorphism.piece_map)
        vertex_map = dict(automorphism.vertex_map)
        if set(piece_map) != set(self.piece_names) or set(piece_map.values()) != set(
            self.piece_names
        ):
            raise ValueError(f"Invalid piece permutation {automorphism.name}")
        if set(vertex_map) != set(self.vertex_names) or set(vertex_map.values()) != set(
            self.vertex_names
        ):
            raise ValueError(f"Invalid vertex permutation {automorphism.name}")

        pieces = self.planar_map.piece_map()
        vertices = self.planar_map.vertex_map()
        orientation_signs = []
        for piece in self.planar_map.pieces:
            target = pieces[piece_map[piece.name]]
            if piece.outer_boundary_contact != target.outer_boundary_contact:
                raise ValueError(
                    f"Automorphism {automorphism.name} changes outer-boundary contact "
                    f"of {piece.name}"
                )
            mapped_cycle = tuple(vertex_map[name] for name in piece.contour_vertices)
            orientation_signs.append(
                _cycle_orientation(mapped_cycle, target.contour_vertices)
            )
        if len(set(orientation_signs)) != 1:
            raise ValueError(
                f"Automorphism {automorphism.name} has inconsistent contour orientation"
            )
        orientation_sign = orientation_signs[0]

        for vertex in self.planar_map.vertices:
            target = vertices[vertex_map[vertex.name]]
            if vertex.kind != target.kind:
                raise ValueError(
                    f"Automorphism {automorphism.name} changes vertex kind of "
                    f"{vertex.name}"
                )
            mapped_incident = {
                piece_map[piece_name] for piece_name in vertex.incident_pieces
            }
            if mapped_incident != set(target.incident_pieces):
                raise ValueError(
                    f"Automorphism {automorphism.name} changes incidence at "
                    f"{vertex.name}"
                )

        edge_to_interface: Dict[Tuple[str, frozenset[str]], str] = {}
        interface_by_name = {
            interface.name: interface for interface in self.planar_map.interfaces
        }
        for interface in self.planar_map.interfaces:
            for view in interface.views:
                edge_to_interface[
                    (view.piece, frozenset((view.start_vertex, view.end_vertex)))
                ] = interface.name

        for interface in self.planar_map.interfaces:
            target_names = set()
            for view in interface.views:
                key = (
                    piece_map[view.piece],
                    frozenset(
                        (
                            vertex_map[view.start_vertex],
                            vertex_map[view.end_vertex],
                        )
                    ),
                )
                target_name = edge_to_interface.get(key)
                if target_name is None:
                    raise ValueError(
                        f"Automorphism {automorphism.name} does not preserve edge "
                        f"{view.piece}:{view.start_vertex}-{view.end_vertex}"
                    )
                target_names.add(target_name)
            if len(target_names) != 1:
                raise ValueError(
                    f"Automorphism {automorphism.name} splits interface {interface.name}"
                )
            target = interface_by_name[next(iter(target_names))]
            if interface.is_outer != target.is_outer:
                raise ValueError(
                    f"Automorphism {automorphism.name} changes interface type of "
                    f"{interface.name}"
                )
            mapped_pieces = {piece_map[view.piece] for view in interface.views}
            target_pieces = {view.piece for view in target.views}
            if mapped_pieces != target_pieces:
                raise ValueError(
                    f"Automorphism {automorphism.name} changes interface incidence of "
                    f"{interface.name}"
                )

        piece_permutation = tuple(
            self.piece_index[piece_map[name]] for name in self.piece_names
        )
        vertex_permutation = tuple(
            self.vertex_index[vertex_map[name]] for name in self.vertex_names
        )
        occurrence_permutation = tuple(
            self.occurrence_index[
                Occurrence(piece_map[occurrence.piece], vertex_map[occurrence.vertex])
            ]
            for occurrence in self.occurrences
        )
        return SymmetryAction(
            name=automorphism.name,
            piece_permutation=piece_permutation,
            vertex_permutation=vertex_permutation,
            occurrence_permutation=occurrence_permutation,
            orientation_sign=orientation_sign,
        )

    def _group_closure(
        self, declared: Sequence[SymmetryAction]
    ) -> Tuple[SymmetryAction, ...]:
        identity = SymmetryAction(
            name="identity",
            piece_permutation=tuple(range(len(self.piece_names))),
            vertex_permutation=tuple(range(len(self.vertex_names))),
            occurrence_permutation=tuple(range(len(self.occurrences))),
            orientation_sign=1,
        )
        actions: Dict[
            Tuple[Tuple[int, ...], Tuple[int, ...]], SymmetryAction
        ] = {identity.key: identity}
        for action in declared:
            actions.setdefault(action.key, action)

        changed = True
        while changed:
            changed = False
            current = tuple(actions.values())
            for left in current:
                for right in current:
                    composed = left.compose(
                        right,
                        name=f"closure_{len(actions)}",
                    )
                    if composed.key not in actions:
                        actions[composed.key] = composed
                        changed = True
                        if len(actions) > 4096:
                            raise ValueError(
                                f"Automorphism closure for {self.planar_map.name} "
                                "exceeds the conservative limit of 4096 elements"
                            )
        return tuple(sorted(actions.values(), key=lambda action: action.key))

    def _effective_mapping_actions(
        self,
        required_action: SymmetryAction | None,
        *,
        required_equivariance_on_weak_orders: bool,
    ) -> Tuple[SymmetryAction, ...]:
        if required_action is None or not required_equivariance_on_weak_orders:
            return self.quotient_group

        identity_key = (
            tuple(range(len(self.piece_names))),
            tuple(range(len(self.vertex_names))),
        )
        subgroup: Dict[
            Tuple[Tuple[int, ...], Tuple[int, ...]], SymmetryAction
        ] = {}
        current = next(action for action in self.group if action.key == identity_key)
        while current.key not in subgroup:
            subgroup[current.key] = current
            current = required_action.compose(
                current,
                name=f"required_power_{len(subgroup)}",
            )

        quotient_by_key = {action.key: action for action in self.quotient_group}
        unseen = set(quotient_by_key)
        representatives = []
        while unseen:
            seed_key = min(unseen)
            seed = quotient_by_key[seed_key]
            coset_keys = {
                seed.compose(element, name="coset").key
                for element in subgroup.values()
            }
            coset_keys &= set(quotient_by_key)
            representative_key = min(coset_keys)
            representatives.append(quotient_by_key[representative_key])
            unseen.difference_update(coset_keys)
        return tuple(representatives)

    def action_by_name(self, name: str) -> SymmetryAction:
        action = self._declared_by_name.get(name)
        if action is None:
            raise ValueError(f"Unknown automorphism {name!r}")
        return action

    def normalize_blocks(
        self,
        blocks: Sequence[Sequence[int]],
        action: SymmetryAction | None = None,
    ) -> Blocks:
        permutation = (
            tuple(range(len(self.occurrences)))
            if action is None
            else action.occurrence_permutation
        )
        mapped = tuple(
            tuple(sorted(permutation[occurrence_id] for occurrence_id in block))
            for block in blocks
        )
        if not mapped:
            return ()

        anchor_block = next(
            (
                index
                for index, block in enumerate(mapped)
                if self.reference_anchor in block
            ),
            None,
        )
        if anchor_block is None:
            raise ValueError("Complete mapping omits the reference anchor occurrence")
        anchored = mapped[anchor_block:] + mapped[:anchor_block]

        reference_order = tuple(
            occurrence_id
            for block in anchored
            for occurrence_id in block
            if self.occurrence_piece_index[occurrence_id]
            == self.reference_piece_index
        )
        direct = self.reference_sequence
        reversed_direct = (direct[0],) + tuple(reversed(direct[1:]))
        if reference_order == direct:
            return anchored
        if reference_order == reversed_direct:
            return (anchored[0],) + tuple(reversed(anchored[1:]))
        raise ValueError(
            "Transformed mapping does not induce a cyclic contour on the reference piece"
        )

    def canonical_mapping_key(self, blocks: Sequence[Sequence[int]]) -> Blocks:
        return min(
            self.normalize_blocks(blocks, action)
            for action in self.mapping_actions
        )

    def is_canonical_mapping(self, blocks: Sequence[Sequence[int]]) -> bool:
        normalized = self.normalize_blocks(blocks)
        return normalized == self.canonical_mapping_key(blocks)


def _cycle_orientation(left: Sequence[str], right: Sequence[str]) -> int:
    left = tuple(left)
    right = tuple(right)
    if len(left) != len(right):
        raise ValueError("Automorphism changes contour length")
    if _cyclic_equal(left, right):
        return 1
    if _cyclic_equal(left, tuple(reversed(right))):
        return -1
    raise ValueError("Automorphism does not preserve a piece contour")


def _cyclic_equal(left: Sequence[str], right: Sequence[str]) -> bool:
    left = tuple(left)
    right = tuple(right)
    if len(left) != len(right):
        return False
    if not left:
        return True
    doubled = right + right
    return any(left == doubled[offset : offset + len(left)] for offset in range(len(left)))
