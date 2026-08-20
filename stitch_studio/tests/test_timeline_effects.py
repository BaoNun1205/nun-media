from __future__ import annotations

import unittest

from stitch_studio.rendering.effects import load_effect_registry, normalized_effect_params


class TimelineEffectsTest(unittest.TestCase):
    def test_registry_normalizes_and_clamps_params(self) -> None:
        identifier, params = normalized_effect_params({"params": {"effectId": "film_grain", "amount": 99, "size": -1}})
        self.assertEqual(identifier, "film_grain")
        self.assertEqual(params["amount"], 0.5)
        self.assertEqual(params["size"], 0.5)

    def test_registry_excludes_removed_procedural_prototypes(self) -> None:
        registry = load_effect_registry()
        self.assertGreaterEqual(len(registry), 20)
        self.assertNotIn("snow", registry)
        self.assertNotIn("rain", registry)
        self.assertNotIn("dust", registry)
        self.assertIn("pixel_sort", registry)
