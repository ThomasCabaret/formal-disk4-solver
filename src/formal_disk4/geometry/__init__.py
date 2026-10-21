"""Numerical realization of one decorated formal piece contour."""

from .model import FormalGeometryProblem, GeometrySolution, parse_formal_geometry_problem
from .placement_audit import (
    EuclideanPartialPlacementPruner,
    EuclideanPlacementAuditConfig,
    EuclideanPlacementAuditResult,
    audit_partial_euclidean_placement,
    audit_euclidean_placement,
)
from .runner import GeometryRunner
from .solver import GeometryAttemptResult, GeometrySolverConfig, NumericalContourSolver

__all__ = [
    "FormalGeometryProblem",
    "EuclideanPartialPlacementPruner",
    "EuclideanPlacementAuditConfig",
    "EuclideanPlacementAuditResult",
    "GeometryAttemptResult",
    "GeometryRunner",
    "GeometrySolution",
    "GeometrySolverConfig",
    "NumericalContourSolver",
    "parse_formal_geometry_problem",
    "audit_partial_euclidean_placement",
    "audit_euclidean_placement",
]
