import unittest

from formal_disk4.enumeration.weak_orders import (
    count_distinct_orders_all_peripheral_phases,
    count_weak_orders_all_peripheral_phases,
    count_weak_orders_fixed_phases,
)


class CountTests(unittest.TestCase):
    def test_distinct_orders(self) -> None:
        self.assertEqual(count_distinct_orders_all_peripheral_phases(), 201_801_600)

    def test_weak_orders(self) -> None:
        self.assertEqual(count_weak_orders_fixed_phases(), 266_645_826)
        self.assertEqual(count_weak_orders_all_peripheral_phases(), 17_065_332_864)


if __name__ == "__main__":
    unittest.main()
