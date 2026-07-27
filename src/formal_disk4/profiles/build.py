from __future__ import annotations

from typing import Sequence

from formal_disk4.enumeration.weak_orders import Placement
from formal_disk4.maps.base import PlanarMap
from formal_disk4.words.compile import CompiledWordCase, build_contact_mappings
from formal_disk4.words.families import ExactFormalFamily, FamilySpecialization

from .canonical import canonical_contour_signature
from .decorations import build_decorations
from .model import FormalProfile


def build_formal_profile(
    planar_map: PlanarMap,
    occurrence_names: Sequence[str],
    placement: Placement,
    compiled: CompiledWordCase,
    family: ExactFormalFamily,
    specialization: FamilySpecialization,
    tolerance: float = 1e-9,
) -> FormalProfile:
    environment = specialization.environment_map()
    terminal_contour, mappings = build_contact_mappings(compiled, environment)
    decorations = build_decorations(
        planar_map=planar_map,
        occurrence_names=occurrence_names,
        placement=placement,
        compiled=compiled,
        environment=environment,
        terminal_contour=terminal_contour,
        mappings=mappings,
        tolerance=tolerance,
    )

    return FormalProfile(
        schema_version="formal-contour-profile-v6",
        map_name=planar_map.name,
        assignment_id=placement.assignment.assignment_id,
        placement_id=placement.placement_id,
        expected_internal_mapping_count=len(planar_map.internal_interfaces()),
        expected_outer_arc_count=len(planar_map.outer_interfaces()),
        family=family,
        specialization=specialization,
        atomic_contour=compiled.contour_word,
        terminal_contour=terminal_contour,
        point_decorations=decorations.points,
        point_classes=decorations.point_classes,
        angle_equations=decorations.angle_equations,
        exact_angle_solution=decorations.exact_angle_solution,
        joint_angular_feasibility=decorations.joint_angular_feasibility,
        curve_components=decorations.curve_components,
        exact_length_solution=decorations.exact_length_solution,
        template_relations=decorations.template_relations,
        contact_mappings=mappings,
        outer_arcs=decorations.outer_arcs,
        formal_constraints=decorations.formal_constraints,
        placement_length_margin=placement.length_margin,
        placement_angle_margin=placement.angle_margin,
        decorated_angle_margin=decorations.angle_margin,
        terminal_length_margin=decorations.terminal_length_margin,
        canonical_contour_signature=canonical_contour_signature(terminal_contour),
        filter_status=(),
    )
