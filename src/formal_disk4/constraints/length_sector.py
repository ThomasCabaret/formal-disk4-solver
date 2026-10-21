"""Homogeneous arclength constraints shared by search and terminal solving."""
from dataclasses import dataclass
from fractions import Fraction


@dataclass(frozen=True)
class LengthSectorRow:
    # Dot product with positive prototype interval lengths equals zero, or is
    # strictly positive. Homogeneity preserves the solver's choice of scale.
    coefficients: tuple[Fraction, ...]
    strict: bool = False

    def to_dict(self):
        return {"coefficients": [str(x) for x in self.coefficients],
                "relation": "positive" if self.strict else "equal"}
