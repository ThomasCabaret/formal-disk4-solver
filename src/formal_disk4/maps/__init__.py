from .base import InterfaceSpec, PieceSpec, PlanarMap, VertexSpec
from .c3 import build_c3_map
from .c4 import build_c4_map
from .centered_two_ring import (
    build_centered_double_cycle_map,
    build_centered_double_cycle_offset_map,
    build_centered_inner_cycle_boundary_points_map,
    build_centered_outer_cycle_center_points_map,
)
from .double_cycle import build_double_cycle_6_map, build_double_cycle_map
from .k4 import build_k4_map
from .k4_minus_arc import build_k4_minus_arc_map
from .k4_minus_point import build_k4_minus_point_map
from .wheel import build_wheel_4_map, build_wheel_map
from .two_ring_families import (
    build_double_cycle_offset_map,
    build_inner_cycle_boundary_points_map,
    build_outer_cycle_center_points_map,
)
from .three_ring_families import (
    build_three_ring_boundary_points_map,
    build_three_ring_inner_offset_map,
    build_three_ring_map,
    build_three_ring_offset_opposite_map,
    build_three_ring_offset_same_map,
    build_three_ring_outer_offset_map,
    build_three_ring_parallel_map,
)

__all__ = [
    "PlanarMap",
    "PieceSpec",
    "VertexSpec",
    "InterfaceSpec",
    "build_c3_map",
    "build_c4_map",
    "build_centered_double_cycle_map",
    "build_centered_double_cycle_offset_map",
    "build_centered_inner_cycle_boundary_points_map",
    "build_centered_outer_cycle_center_points_map",
    "build_double_cycle_map",
    "build_double_cycle_6_map",
    "build_double_cycle_offset_map",
    "build_inner_cycle_boundary_points_map",
    "build_outer_cycle_center_points_map",
    "build_three_ring_map",
    "build_three_ring_parallel_map",
    "build_three_ring_boundary_points_map",
    "build_three_ring_outer_offset_map",
    "build_three_ring_inner_offset_map",
    "build_three_ring_offset_same_map",
    "build_three_ring_offset_opposite_map",
    "build_k4_map",
    "build_k4_minus_point_map",
    "build_k4_minus_arc_map",
    "build_wheel_4_map",
    "build_wheel_map",
]

# Source-level compatibility for notebooks and scripts written before 1.0.0.
build_k3_pizza_map = build_c3_map
build_k4_pizza_map = build_c4_map
build_k4_central_map = build_k4_map
