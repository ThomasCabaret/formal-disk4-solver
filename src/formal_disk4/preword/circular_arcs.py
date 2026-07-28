"""Compatibility layer for the pre-0.9 circular-arc module name."""

from formal_disk4.preword.arc_topology import (
    CircularInterval,
    RadiusArcTopologyFilter,
    RadiusArcTopologyResult,
)


class CircularArcPrewordFilter(RadiusArcTopologyFilter):
    """Accept the legacy constructor while using the refactored topology filter."""

    def __init__(
        self,
        *,
        length_oracle=None,
        enable_signed_balance=None,
        **kwargs,
    ) -> None:
        # The 0.9 metric system replaces the old standalone signed-balance test.
        # ``length_oracle`` is ignored because the topology module owns its
        # conservative floating screen and exact rejection certificate.
        del length_oracle, enable_signed_balance
        super().__init__(**kwargs)


CircularArcPrewordResult = RadiusArcTopologyResult

__all__ = [
    "CircularInterval",
    "CircularArcPrewordFilter",
    "CircularArcPrewordResult",
    "RadiusArcTopologyFilter",
    "RadiusArcTopologyResult",
]
