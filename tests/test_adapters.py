from __future__ import annotations

import unittest
from dataclasses import replace

from presence_engine.adapters import (
    AdapterEnvelope,
    EntityStateAdapter,
    FrigateEventAdapter,
    FrigateFaceAdapter,
    PTZContextAdapter,
)
from presence_engine.configuration import AdapterType, parse_configuration
from presence_engine.temporal import TemporalCameraRegistry

from helpers import at
from integration_helpers import integration_config


class AdapterTests(unittest.TestCase):
    def setUp(self) -> None:
        self.config = integration_config()

    def test_frigate_event_prefers_current_zone_over_profile(self) -> None:
        contexts = TemporalCameraRegistry(dict(self.config.cameras))
        contexts.update("camera_a", role="profile", state="profile_alpha", observed_at=at(-2))
        contexts.update("camera_a", role="movement", state="Available", observed_at=at(-1))
        definition = next(
            source for source in self.config.sources if source.adapter is AdapterType.FRIGATE_EVENTS
        )
        adapter = FrigateEventAdapter(definition, self.config.cameras, contexts)
        envelope = AdapterEnvelope(
            "mqtt",
            "frigate/events",
            {
                "type": "update",
                "after": {
                    "id": "event-a",
                    "camera": "camera_a",
                    "label": "person",
                    "start_time": at(-5).timestamp(),
                    "frame_time": at(0).timestamp(),
                    "end_time": None,
                    "current_zones": ["zone_beta"],
                    "entered_zones": ["zone_alpha", "zone_beta"],
                },
            },
            at(0),
            at(1),
        )

        result = adapter.parse(envelope)

        self.assertEqual(result.observations[0].location.area, "beta")
        self.assertEqual(result.observations[0].detected_at, at(-5))
        self.assertEqual(result.observations[0].location.observed_at, at(0))

    def test_zero_count_ends_source_observation(self) -> None:
        definition = next(
            source for source in self.config.sources if source.source_id == "area_count"
        )
        adapter = EntityStateAdapter(definition)
        envelope = AdapterEnvelope(
            "state",
            "sensor.area_count",
            {"state": "0", "last_changed": at(-2).isoformat()},
            at(0),
            at(0),
        )

        result = adapter.parse(envelope)

        self.assertEqual(result.observations[0].status.value, "ended")
        self.assertEqual(result.observations[0].count.maximum, 0)

    def test_face_attempt_below_threshold_is_not_an_identity_revision(self) -> None:
        definition = next(
            source for source in self.config.sources if source.adapter is AdapterType.FRIGATE_FACE
        )
        adapter = FrigateFaceAdapter(definition)

        result = adapter.parse(
            AdapterEnvelope(
                "mqtt",
                "frigate/tracked_object_update",
                {
                    "type": "face",
                    "id": "event-a",
                    "camera": "camera_a",
                    "name": "person_a",
                    "score": 0.40,
                    "timestamp": at(2).timestamp(),
                },
                at(2),
                at(2),
            )
        )

        self.assertTrue(result.ignored)
        self.assertEqual(result.observations, ())

    def test_face_identity_is_normalized_by_explicit_mapping(self) -> None:
        definition = next(
            source for source in self.config.sources if source.adapter is AdapterType.FRIGATE_FACE
        )
        adapter = FrigateFaceAdapter(
            replace(
                definition,
                options={
                    "recognition_threshold": 0.8,
                    "identity_map": {"Person A Display": "person_a"},
                },
            )
        )

        result = adapter.parse(
            AdapterEnvelope(
                "mqtt",
                "frigate/tracked_object_update",
                {
                    "type": "face",
                    "id": "event-a",
                    "camera": "camera_a",
                    "name": "Person A Display",
                    "score": 0.91,
                    "timestamp": at(2).timestamp(),
                },
                at(2),
                at(2),
            )
        )

        self.assertEqual(result.observations[0].identity.value, "person_a")

    def test_bermuda_not_home_removes_location_instead_of_creating_area(self) -> None:
        definition = next(
            source for source in self.config.sources if source.source_id == "device_area"
        )
        result = EntityStateAdapter(definition).parse(
            AdapterEnvelope(
                "state",
                "sensor.device_area",
                {"state": "not_home"},
                at(2),
                at(2),
            )
        )

        self.assertEqual(result.remove_source_ids, ("device_area",))
        self.assertEqual(result.observations, ())

    def test_source_health_reports_availability_without_presence(self) -> None:
        definition = parse_configuration(
            {
                "schema_version": 1,
                "areas": {},
                "adjacency": {},
                "sources": [
                    {
                        "source_id": "scanner_health",
                        "adapter": "source_health",
                        "entity_ids": ["binary_sensor.scanner_online"],
                        "options": {"healthy_states": ["on"]},
                    }
                ],
            }
        ).sources[0]
        adapter = EntityStateAdapter(definition)

        healthy = adapter.parse(
            AdapterEnvelope(
                "state",
                "binary_sensor.scanner_online",
                {"state": "on"},
                at(2),
                at(2),
            )
        )
        unhealthy = adapter.parse(
            AdapterEnvelope(
                "state",
                "binary_sensor.scanner_online",
                {"state": "off"},
                at(3),
                at(3),
            )
        )

        self.assertEqual(healthy.observations, ())
        self.assertEqual(healthy.source_availability[0].available, True)
        self.assertEqual(unhealthy.observations, ())
        self.assertEqual(unhealthy.source_availability[0].available, False)
        self.assertEqual(unhealthy.remove_source_ids, ("scanner_health",))

    def test_source_health_can_treat_any_non_failure_state_as_healthy(self) -> None:
        definition = parse_configuration(
            {
                "schema_version": 1,
                "areas": {},
                "adjacency": {},
                "sources": [
                    {
                        "source_id": "scanner_health",
                        "adapter": "source_health",
                        "entity_ids": ["media_player.scanner"],
                    }
                ],
            }
        ).sources[0]
        adapter = EntityStateAdapter(definition)

        idle = adapter.parse(
            AdapterEnvelope(
                "state", "media_player.scanner", {"state": "idle"}, at(2), at(2)
            )
        )
        unavailable = adapter.parse(
            AdapterEnvelope(
                "state",
                "media_player.scanner",
                {"state": "unavailable"},
                at(3),
                at(3),
            )
        )

        self.assertTrue(idle.source_availability[0].available)
        self.assertFalse(unavailable.source_availability[0].available)

    def test_person_home_ignores_a_configured_tracker_prefix(self) -> None:
        definition = parse_configuration(
            {
                "schema_version": 1,
                "areas": {},
                "adjacency": {},
                "sources": [
                    {
                        "source_id": "person_owner",
                        "adapter": "person_home",
                        "entity_ids": ["person.owner"],
                        "identity": "owner",
                        "options": {
                            "ignored_source_prefixes": ["device_tracker.indoor_"]
                        },
                    }
                ],
            }
        ).sources[0]
        adapter = EntityStateAdapter(definition)

        ignored = adapter.parse(
            AdapterEnvelope(
                "state",
                "person.owner",
                {
                    "state": "home",
                    "attributes": {"source": "device_tracker.indoor_owner"},
                },
                at(2),
                at(2),
            )
        )
        accepted = adapter.parse(
            AdapterEnvelope(
                "state",
                "person.owner",
                {
                    "state": "home",
                    "attributes": {"source": "device_tracker.mobile_owner"},
                },
                at(3),
                at(3),
            )
        )

        self.assertEqual(ignored.remove_source_ids, ("person_owner",))
        self.assertEqual(ignored.observations, ())
        self.assertEqual(accepted.observations[0].identity.value, "owner")
        self.assertEqual(accepted.observations[0].status.value, "active")

    def test_unavailable_ptz_telemetry_invalidates_previous_room_context(self) -> None:
        contexts = TemporalCameraRegistry(dict(self.config.cameras))
        camera = self.config.cameras["camera_a"]
        adapter = PTZContextAdapter(camera, contexts)
        for entity_id, state, second in (
            ("select.camera_profile", "profile_alpha", 0),
            ("sensor.camera_motion_state", "Available", 1),
            ("sensor.camera_motion_state", "unavailable", 2),
        ):
            adapter.parse(
                AdapterEnvelope("state", entity_id, {"state": state}, at(second), at(second))
            )

        context = contexts.latest("camera_a")

        self.assertIsNotNone(context)
        self.assertFalse(context.telemetry_valid)
        self.assertFalse(context.physical_profile_confirmed)


if __name__ == "__main__":
    unittest.main()
