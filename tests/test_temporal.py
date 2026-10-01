from __future__ import annotations

import unittest

from presence_engine.temporal import TemporalCameraRegistry

from helpers import at
from integration_helpers import integration_config


class TemporalRegistryTests(unittest.TestCase):
    def test_measured_interval_refines_only_bracketed_frame(self):
        registry = TemporalCameraRegistry(dict(integration_config().cameras))
        registry.update("camera_a", role="movement", state="Moving", observed_at=at(0))
        registry.record_interval("camera_a", destination="profile_beta", start=at(1), end=at(2))
        self.assertTrue(registry.at("camera_a", at(0.9)).moving)
        measured = registry.at("camera_a", at(1.5))
        self.assertFalse(measured.moving)
        self.assertEqual(measured.profile, "profile_beta")
        self.assertTrue(measured.physical_profile_confirmed)
        self.assertTrue(registry.at("camera_a", at(2.1)).moving)
        saved = registry.export()
        restored = TemporalCameraRegistry(dict(integration_config().cameras))
        restored.restore(saved)
        self.assertEqual(restored.at("camera_a", at(1.5)), measured)
        self.assertFalse(registry.record_interval("camera_a", destination="profile_beta", start=at(1), end=at(2)))
        registry.update("camera_a", role="preset", state="preset_alpha", observed_at=at(1.2))
        self.assertTrue(registry.at("camera_a", at(1.5)).moving)

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
