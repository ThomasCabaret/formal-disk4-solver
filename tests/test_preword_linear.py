from fractions import Fraction
import unittest

from formal_disk4.constraints.hybrid_linear import (
    HybridMarginOracle,
    LinearConstraint,
)
from formal_disk4.maps import build_k3_pizza_map, build_k4_central_map
from formal_disk4.preword.linear_invariants import _safe_sqrt_upper_bound


class HybridPrewordLinearTests(unittest.TestCase):
    def test_rejection_is_exactly_certified(self) -> None:
        # x >= delta and x = 0 permit no positive strict margin.
        oracle = HybridMarginOracle()
        result = oracle.analyze(
            variable_domains=("nonnegative", "nonnegative"),
            equalities=(LinearConstraint.build((1, 0), 0),),
            inequalities=(
                LinearConstraint.build((-1, 1), 0),
                LinearConstraint.build((0, 1), 1),
            ),
            margin_index=1,
        )
        self.assertFalse(result.feasible)
        self.assertTrue(result.exact_certificate_used)
        self.assertEqual(result.margin, Fraction(0))

    def test_non_square_isoperimetric_bound_is_sound(self) -> None:
        bound = _safe_sqrt_upper_bound(3, 1000)
        self.assertGreaterEqual(float(bound * bound), 3.0)
        self.assertEqual(_safe_sqrt_upper_bound(4, 1000), Fraction(2))

    def test_stein_only_concavity_hypothesis(self) -> None:
        self.assertTrue(
            build_k4_central_map().hypotheses.requires_radius_r_concavity
        )
        self.assertFalse(
            build_k3_pizza_map().hypotheses.requires_radius_r_concavity
        )


if __name__ == "__main__":
    unittest.main()
