from __future__ import annotations

"""Bridge from a contact type to the existing word/profile/geometry kernel."""

from formal_disk4.constraints.angle_lp import AngleEquation, AngleInequality
from formal_disk4.enumeration.assignments import AssignmentEnumerator
from formal_disk4.enumeration.weak_orders import Placement
from formal_disk4.maps.base import PlanarMap
from .contact_types import ContactType, ContactTypeSearch
from .contact_model import ContactModel
from formal_disk4.constraints.length_sector import LengthSectorRow
from fractions import Fraction


class PlacementAdapter:
    def __init__(self, planar_map: PlanarMap, *, allow_reflections: bool = True) -> None:
        self.planar_map = planar_map
        self.assignments = AssignmentEnumerator(planar_map, allow_reflections=allow_reflections,
                                                symmetry_mode="off")
        self.occurrences = planar_map.occurrences()
        self.occurrence_index = {o: i for i, o in enumerate(self.occurrences)}
        self.piece_index = {p.name: i for i, p in enumerate(planar_map.pieces)}

    def project_sector(self, contact_type, positions):
        """Translate contact coordinates into homogeneous prototype gap rows.

        Search uses perimeter=1; replace its constant by the sum of all gaps,
        not a literal 1 in disk-circumference units. Offsets are positive-chart
        start coordinates; interface lengths ignore traversal parity.
        """
        if not contact_type.sector:
            return ()
        size = len(contact_type.blocks)
        model = ContactModel(self.planar_map)
        images = []
        for interface in self.planar_map.interfaces:
            view = interface.views[0]
            a, b = (positions[self.occurrence_index[o]] for o in
                    (view.start_occurrence, view.end_occurrence))
            if contact_type.charts[self.piece_index[view.piece]].parity < 0:
                a, b = b, a
            row = [0] * size
            while a != b:
                row[a] = 1
                a = (a+1) % size
            images.append(row)
        for i, chart in enumerate(contact_type.charts):
            if i != model.reference_index:
                start = positions[chart.sequence[0]]
                images.append([int(j < start) for j in range(size)])
        rows = []
        for form, strict in contact_type.sector:
            if len(form.coefficients) != len(images):
                raise ValueError("Sector coordinate dimension mismatch")
            rows.append(LengthSectorRow(tuple(Fraction(form.constant) + sum(
                Fraction(c)*image[j] for c, image in zip(form.coefficients, images))
                for j in range(size)), strict))
        return tuple(rows)

    def materialize(self, contact_type: ContactType, placement_id: int) -> Placement:
        size = len(contact_type.blocks)
        positions = [-1] * len(self.occurrences)
        for block_index, block in enumerate(contact_type.blocks):
            for o in block:
                if positions[o] != -1:
                    raise ValueError("Repeated direct incidence")
                positions[o] = block_index
        if -1 in positions:
            raise ValueError("Incomplete contact type")
        sequences = tuple(tuple(o for block in contact_type.blocks for o in block
                                if self.occurrences[o].piece == p.name)
                          for p in self.planar_map.pieces)
        assignment_id = self.assignments.assignment_id_for_sequences(sequences)
        if assignment_id is None:
            raise ValueError("Contact type has no admissible contour chart")
        assignment = self.assignments.assignment_at(assignment_id)
        rows = []
        for interface in self.planar_map.internal_interfaces():
            arcs = []
            for view in interface.views:
                a, b = (positions[self.occurrence_index[o]]
                        for o in (view.start_occurrence, view.end_occurrence))
                if assignment.orientation_signs[self.piece_index[view.piece]] < 0:
                    a, b = b, a
                if a == b:
                    raise ValueError("Nondegenerate contact collapsed")
                arc = [0] * size
                while a != b:
                    arc[a] = 1
                    a = (a + 1) % size
                arcs.append(arc)
            rows.append(tuple(a - b for a, b in zip(*arcs)))
        equations, inequalities = [], []
        for vertex in self.planar_map.vertices:
            counts = [0] * size
            degree = 0
            for o, occurrence in enumerate(self.occurrences):
                if occurrence.vertex == vertex.name:
                    counts[positions[o]] += 1
                    degree += 1
            if vertex.solid_angle_relation == "equal":
                equations.append(AngleEquation(tuple(counts),
                                  float(degree - vertex.solid_angle_limit_pi)))
            else:
                inequalities.append(AngleInequality(tuple(-v for v in counts),
                                     float(vertex.solid_angle_limit_pi - degree)))
        return Placement(placement_id=placement_id, assignment=assignment,
                         blocks=contact_type.blocks, positions=tuple(positions),
                         length_rows=tuple(rows), length_margin=0.0, length_witness=(),
                         length_sector=self.project_sector(contact_type, positions),
                         angle_equations=tuple(equations), angle_inequalities=tuple(inequalities),
                         angle_margin=0.0, angle_witness=())


class ContactArrangementEnumerator:
    """Streaming compatibility boundary; enumeration lives in ContactTypeSearch."""

    def __init__(self, planar_map: PlanarMap, *, allow_reflections=True, **kwargs) -> None:
        if planar_map.prototype_rotation_order != 1:
            raise ValueError("Contact V2 does not yet support imposed intrinsic prototype rotation")
        self.progress_snapshot: dict = {}

        def progress(snapshot):
            self.progress_snapshot = snapshot

        self.search = ContactTypeSearch(planar_map, allow_reflections=allow_reflections,
                                       progress_sink=progress, **kwargs)
        self.adapter = PlacementAdapter(planar_map, allow_reflections=allow_reflections)
        self.max_nodes = self.search.max_nodes

    @property
    def statistics(self):
        return self.search.statistics

    def enumerate(self):
        for i, contact_type in enumerate(self.search.enumerate()):
            yield self.adapter.materialize(contact_type, i)
