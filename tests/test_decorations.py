import unittest

from formal_disk4.profiles.decorations import (
    MIRROR,
    TemplateTransform,
    _curve_components,
)
from formal_disk4.words.algebra import Literal


class DecorationTests(unittest.TestCase):
    def test_self_mirror_forces_straight_component(self) -> None:
        contour = (Literal("X"),)
        components, component_by_variable = _curve_components(
            contour,
            (("X", "X", MIRROR, "test-interface", 0),),
        )
        self.assertEqual(component_by_variable["X"], 0)
        self.assertEqual(components[0][4], "straight")
        self.assertIn(MIRROR, components[0][3])

    def test_reverse_and_mirror_turn_signs(self) -> None:
        self.assertEqual(TemplateTransform().turn_sign, 1)
        self.assertEqual(TemplateTransform(reverse=True).turn_sign, -1)
        self.assertEqual(TemplateTransform(mirror=True).turn_sign, -1)
        self.assertEqual(TemplateTransform(reverse=True, mirror=True).turn_sign, 1)


if __name__ == "__main__":
    unittest.main()
