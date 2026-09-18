from __future__ import annotations

import unittest

from presence_engine.temporal import TemporalCameraRegistry

from helpers import at
from integration_helpers import integration_config


class TemporalRegistryTests(unittest.TestCase):
    def test_queries_multiple_states_back(self) -> None:
        registry = TemporalCameraRegistry(dict(integration_config().cameras))
        registry.update("camera_a", role="profile", state="profile_alpha", observed_at=at(-20))
        registry.update("camera_a", role="movement", state="Available", observed_at=at(-19))
        registry.update("camera_a", role="movement", state="Moving", observed_at=at(-10))
        registry.update("camera_a", role="profile", state="profile_beta", observed_at=at(-5))
        registry.update("camera_a", role="movement", state="Available", observed_at=at(-4))

        old = registry.at("camera_a", at(-15))
        moving = registry.at("camera_a", at(-8))
        current = registry.at("camera_a", at(0))

        self.assertEqual(old.profile, "profile_alpha")
        self.assertTrue(old.physical_profile_confirmed)
        self.assertTrue(moving.moving)
        self.assertEqual(current.profile, "profile_beta")
        self.assertTrue(current.physical_profile_confirmed)

    def test_out_of_order_field_is_visible_to_later_context(self) -> None:
        registry = TemporalCameraRegistry(dict(integration_config().cameras))
        registry.update("camera_a", role="movement", state="Available", observed_at=at(-4))
        registry.update("camera_a", role="profile", state="profile_alpha", observed_at=at(-5))

        current = registry.at("camera_a", at(0))

        self.assertEqual(current.profile, "profile_alpha")
        self.assertTrue(current.physical_profile_confirmed)


if __name__ == "__main__":
    unittest.main()
