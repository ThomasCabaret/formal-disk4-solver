"""Bounded, learning-guided exploration of complete contour mappings."""

from .core import (
    LabEvaluation,
    MappingCandidate,
    MappingSpace,
    CompleteMappingEvaluator,
)
from .runner import CampaignResult, MappingLabRunner

__all__ = [
    "CompleteMappingEvaluator",
    "LabEvaluation",
    "MappingCandidate",
    "MappingLabRunner",
    "MappingSpace",
    "CampaignResult",
]
