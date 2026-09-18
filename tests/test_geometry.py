from __future__ import annotations

import unittest

from presence_engine import CameraGeometry, GeometryContext, Quality, SpatialLevel, resolve_camera_location

from helpers import at


class GeometryTests(unittest.TestCase):
    def setUp(self) -> None:
        self.geometry=CameraGeometry(
            floor="floor_alpha",
            zone_to_area={"zone_a":"alpha","zone_b":"beta"},
            profile_to_area={"profile_a":"alpha","profile_b":"beta"},
        )

    def test_current_zone_has_priority_over_profile(self) -> None:
        claim=resolve_camera_location(GeometryContext(
            context_id="ctx-1",
            observed_at=at(1),
            current_zones=("zone_b",),
            entered_zones=("zone_a",),
            profile="profile_a",
            physical_profile_confirmed=True,
        ),self.geometry)
        self.assertEqual(claim.area,"beta")
        self.assertEqual(claim.method,"frigate_current_zone")
        self.assertEqual(claim.quality,Quality.HIGH)

    def test_entered_zone_is_not_current_location(self) -> None:
        claim=resolve_camera_location(GeometryContext(
            context_id="ctx-2",
            observed_at=at(2),
            entered_zones=("zone_b",),
        ),self.geometry)
        self.assertEqual(claim.level,SpatialLevel.FLOOR)
        self.assertEqual(claim.method,"camera_scope_only")

    def test_moving_never_uses_requested_or_previous_profile(self) -> None:
        claim=resolve_camera_location(GeometryContext(
            context_id="ctx-3",
            observed_at=at(3),
            profile="profile_b",
            preset="beta",
            moving=True,
            physical_profile_confirmed=True,
        ),self.geometry)
        self.assertEqual(claim.level,SpatialLevel.FLOOR)
        self.assertEqual(claim.method,"ptz_transition")
        self.assertEqual(claim.quality,Quality.UNKNOWN)

    def test_profile_fallback_requires_physical_confirmation(self) -> None:
        unconfirmed=resolve_camera_location(GeometryContext(
            context_id="ctx-4",
            observed_at=at(4),
            profile="profile_b",
        ),self.geometry)
        confirmed=resolve_camera_location(GeometryContext(
            context_id="ctx-5",
            observed_at=at(5),
            profile="profile_b",
            physical_profile_confirmed=True,
        ),self.geometry)
        self.assertEqual(unconfirmed.level,SpatialLevel.FLOOR)
        self.assertEqual(confirmed.area,"beta")
        self.assertEqual(confirmed.method,"ptz_profile_fallback")

    def test_multiple_current_zones_are_explicitly_ambiguous(self) -> None:
        claim=resolve_camera_location(GeometryContext(
            context_id="ctx-6",
            observed_at=at(6),
            current_zones=("zone_a","zone_b"),
        ),self.geometry)
        self.assertEqual(claim.level,SpatialLevel.FLOOR)
        self.assertEqual(claim.candidates,("alpha","beta"))


if __name__ == "__main__":
    unittest.main()

