from __future__ import annotations

"""Metric coordinates of contacts, before any prototype weak order exists."""

from dataclasses import dataclass

from formal_disk4.maps.base import PlanarMap
from .linear import Form, LinearState


@dataclass(frozen=True)
class Chart:
    piece: int
    parity: int
    cut: int
    sequence: tuple[int, ...]
    coordinates: tuple[Form, ...]


class ContactModel:
    """One positive length per physical interface, shared by its two views.

    Every tile perimeter is one from the root, including tiles whose chart is
    still unknown. A chart specifies parity and its first marked point after
    the prototype cut. All its coordinates are then offset + prefix lengths.
    This is a finite, exhaustive representation of direct marked incidences;
    it does not assert finiteness of derived cuts in the residual word problem.
    """

    def __init__(self, planar_map: PlanarMap) -> None:
        self.planar_map = planar_map
        self.occurrences = planar_map.occurrences()
        self.occurrence_index = {o: i for i, o in enumerate(self.occurrences)}
        self.piece_names = tuple(p.name for p in planar_map.pieces)
        self.reference_index = self.piece_names.index(planar_map.reference_piece)
        piece_index = {p: i for i, p in enumerate(self.piece_names)}
        self.base_sequences = tuple(tuple(i for i, o in enumerate(self.occurrences)
                                          if o.piece == p) for p in self.piece_names)
        if any(len(s) < 3 for s in self.base_sequences):
            raise ValueError("Contact search currently requires at least three marked vertices per tile")
        self.width = len(planar_map.interfaces) + len(planar_map.pieces) - 1
        self.zero = Form.scalar(self.width, 0)
        self.one = Form.scalar(self.width, 1)
        self.lengths = tuple(Form.variable(self.width, i)
                             for i in range(len(planar_map.interfaces)))
        cursor = len(self.lengths)
        offsets = []
        for i in range(len(self.piece_names)):
            if i == self.reference_index:
                offsets.append(self.zero)
            else:
                offsets.append(Form.variable(self.width, cursor))
                cursor += 1
        self.offsets = tuple(offsets)
        edge_indices = {}
        neighbors = [set() for _ in self.piece_names]
        for edge, interface in enumerate(planar_map.interfaces):
            for view in interface.views:
                key = (view.piece, frozenset((view.start_vertex, view.end_vertex)))
                if key in edge_indices:
                    raise ValueError("Multiple interface components with identical endpoints are unsupported")
                edge_indices[key] = edge
            if interface.right_piece is not None:
                i, j = piece_index[interface.left_piece], piece_index[interface.right_piece]
                neighbors[i].add(j)
                neighbors[j].add(i)
        self.neighbors = tuple(frozenset(n) for n in neighbors)
        self.contour_edges = tuple(tuple(edge_indices[(p.name, frozenset((a, b)))]
                                        for a, b in p.directed_edges())
                                   for p in planar_map.pieces)
        # Interface lengths are arclengths. Congruence identifies each pair and
        # equal perimeters give these equations regardless of reflections.
        root = LinearState(strict=self.lengths)
        for edges in self.contour_edges:
            perimeter = self.zero
            for edge in edges:
                perimeter = perimeter + self.lengths[edge]
            root = root.equal(perimeter - self.one)
        for i, offset in enumerate(self.offsets):
            if i != self.reference_index:
                root = root.nonnegative(offset).positive(self.one - offset)
        self.root_state = root

    def chart(self, piece: int, parity: int, cut: int) -> Chart:
        if parity not in (-1, 1):
            raise ValueError("Chart parity must be +1 or -1")
        base = self.base_sequences[piece]
        sequence = base if parity == 1 else tuple(reversed(base))
        sequence = sequence[cut:] + sequence[:cut]
        position = {o: i for i, o in enumerate(base)}
        coordinates = [self.offsets[piece]]
        for a, b in zip(sequence, sequence[1:]):
            edge_index = position[a] if parity == 1 else position[b]
            length = self.lengths[self.contour_edges[piece][edge_index]]
            coordinates.append(coordinates[-1] + length)
        return Chart(piece, parity, cut, sequence, tuple(coordinates))

    def select_chart(self, state: LinearState, chart: Chart) -> LinearState:
        # Last marked position is strictly below the prototype cut at 1.
        # Together with shared positive lengths, this enforces the whole local
        # cyclic order without enumerating a merge with other tile contours.
        return state.positive(self.one - chart.coordinates[-1])
