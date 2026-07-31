from fractions import Fraction
import random
import unittest

from formal_disk4.constraints.hybrid_linear import (
    HybridLinearResult,
    HybridMarginOracle,
    LinearConstraint,
)
from formal_disk4.constraints.rational_lp import RationalSimplex
from formal_disk4.maps import build_c3_map, build_k4_map
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


    @staticmethod
    def _legacy_exact(
        domains, equalities, inequalities, margin_index
    ) -> HybridLinearResult:
        columns = []
        expanded_width = 0
        for domain in domains:
            if domain == "nonnegative":
                columns.append((expanded_width, None))
                expanded_width += 1
            else:
                columns.append((expanded_width, expanded_width + 1))
                expanded_width += 2

        def expand(coefficients):
            row = [Fraction(0) for _ in range(expanded_width)]
            for coefficient, (positive, negative) in zip(coefficients, columns):
                row[positive] += coefficient
                if negative is not None:
                    row[negative] -= coefficient
            return row

        matrix = []
        rhs = []
        for item in equalities:
            row = expand(item.coefficients)
            matrix.extend((row, [-value for value in row]))
            rhs.extend((item.rhs, -item.rhs))
        for item in inequalities:
            matrix.append(expand(item.coefficients))
            rhs.append(item.rhs)
        objective = [Fraction(0) for _ in range(expanded_width)]
        positive, negative = columns[margin_index]
        objective[positive] = 1
        if negative is not None:
            objective[negative] = -1
        solution = RationalSimplex(matrix, rhs, objective).solve()
        return HybridLinearResult(
            solution.status == "optimal"
            and solution.optimum is not None
            and solution.optimum > 0,
            solution.optimum,
            f"exact:{solution.status}",
            True,
        )

    def test_exact_equality_elimination_matches_legacy_simplex(self) -> None:
        rng = random.Random(731_991)
        oracle = HybridMarginOracle()
        for _case in range(80):
            width = rng.randint(2, 6)
            domains = tuple(
                "nonnegative" if rng.random() < 0.7 else "free"
                for _ in range(width)
            )
            margin_index = rng.randrange(width)
            domains = tuple(
                "nonnegative" if index == margin_index else domain
                for index, domain in enumerate(domains)
            )
            equalities = tuple(
                LinearConstraint.build(
                    tuple(rng.randint(-2, 2) for _ in range(width)),
                    rng.randint(-2, 2),
                )
                for _ in range(rng.randint(0, width + 1))
            )
            inequalities = tuple(
                LinearConstraint.build(
                    tuple(rng.randint(-2, 2) for _ in range(width)),
                    rng.randint(-3, 3),
                )
                for _ in range(rng.randint(1, width + 3))
            )
            legacy = self._legacy_exact(
                domains, equalities, inequalities, margin_index
            )
            reduced = oracle._solve_exact(
                domains, equalities, inequalities, margin_index
            )
            self.assertEqual(reduced.feasible, legacy.feasible)
            self.assertEqual(reduced.status, legacy.status)
            self.assertEqual(reduced.margin, legacy.margin)

    def test_non_square_isoperimetric_bound_is_sound(self) -> None:
        bound = _safe_sqrt_upper_bound(3, 1000)
        self.assertGreaterEqual(float(bound * bound), 3.0)
        self.assertEqual(_safe_sqrt_upper_bound(4, 1000), Fraction(2))

    def test_stein_only_concavity_hypothesis(self) -> None:
        self.assertTrue(
            build_k4_map().hypotheses.requires_radius_r_concavity
        )
        self.assertFalse(
            build_c3_map().hypotheses.requires_radius_r_concavity
        )


if __name__ == "__main__":
    unittest.main()
