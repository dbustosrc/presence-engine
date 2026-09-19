from __future__ import annotations

import unittest
from dataclasses import replace

from presence_engine.adapters import AdapterEnvelope
from presence_engine.runtime import PresenceRuntime
from presence_engine.configuration import EngineConfiguration, parse_configuration

from helpers import at
from integration_helpers import integration_config


class RuntimeTests(unittest.TestCase):
    def setUp(self) -> None:
        self.runtime = PresenceRuntime(integration_config(), now=lambda: at(10))
        for entity_id, state, second in (
            ("select.camera_profile", "profile_alpha", -3),
            ("select.camera_preset", "preset_alpha", -2),
            ("sensor.camera_motion_state", "Available", -1),
        ):
            self.runtime.process(
                AdapterEnvelope(
                    "state",
                    entity_id,
                    {"state": state},
                    at(second),
                    at(second),
                )
            )

    def test_event_and_late_face_become_one_presence_and_one_detection(self) -> None:
        event = AdapterEnvelope(
            "mqtt",
            "frigate/events",
            {
                "type": "update",
                "after": {
                    "id": "event-a",
                    "camera": "camera_a",
                    "label": "person",
                    "start_time": at(0).timestamp(),
                    "frame_time": at(1).timestamp(),
                    "end_time": None,
                    "current_zones": ["zone_alpha"],
                    "entered_zones": ["zone_alpha"],
                },
            },
            at(1),
            at(1),
        )
        self.runtime.process(event)
        face = AdapterEnvelope(
            "mqtt",
            "frigate/tracked_object_update",
            {
                "type": "face",
                "id": "event-a",
                "camera": "camera_a",
                "name": "person_a",
                "score": 0.92,
                "timestamp": at(7).timestamp(),
            },
            at(7),
            at(8),
        )

        update = self.runtime.process(face)

        self.assertEqual((update.snapshot.count_minimum, update.snapshot.count_maximum), (1, 1))
        self.assertEqual(update.snapshot.presences[0].identity, "person_a")
        self.assertEqual(update.snapshot.presences[0].location.area, "alpha")
        self.assertEqual(update.detections[0].detected_at, at(0))
        self.assertEqual(update.detections[0].recognized_at, at(7))
        self.assertEqual(update.detections[0].revision, 2)
        self.assertIn("person_a", self.runtime.latest_images)

    def test_duplicate_event_does_not_publish_another_detection_revision(self) -> None:
        event = AdapterEnvelope(
            "mqtt",
            "frigate/events",
            {
                "type": "update",
                "after": {
                    "id": "event-duplicate",
                    "camera": "camera_a",
                    "label": "person",
                    "start_time": at(0).timestamp(),
                    "frame_time": at(1).timestamp(),
                    "end_time": None,
                    "current_zones": ["zone_alpha"],
                },
            },
            at(1),
            at(1),
        )

        first = self.runtime.process(event)
        duplicate = self.runtime.process(event)

        self.assertEqual(first.detections[0].revision, 1)
        self.assertEqual(duplicate.detections, ())
        self.assertFalse(duplicate.changed)

    def test_bad_payload_isolated_without_losing_other_sources(self) -> None:
        device = AdapterEnvelope(
            "state",
            "sensor.device_area",
            {"state": "Alpha Room"},
            at(0),
            at(0),
        )
        self.runtime.process(device)
        bad = AdapterEnvelope(
            "mqtt",
            "frigate/events",
            {"type": "update", "after": {"camera": "camera_a"}},
            at(1),
            at(1),
        )

        update = self.runtime.process(bad)

        self.assertEqual(update.snapshot.count_minimum, 1)
        self.assertEqual(update.failures[0].source_id, "frigate_events")
        self.assertTrue(update.snapshot.coverage_degraded)

        recovered = self.runtime.process(
            AdapterEnvelope(
                "mqtt",
                "frigate/events",
                {
                    "type": "update",
                    "after": {
                        "id": "event-after-bad-payload",
                        "camera": "camera_a",
                        "label": "person",
                        "start_time": at(2).timestamp(),
                        "frame_time": at(2).timestamp(),
                        "end_time": None,
                        "current_zones": ["zone_alpha"],
                    },
                },
                at(2),
                at(2),
            )
        )
        self.assertFalse(recovered.snapshot.coverage_degraded)

    def test_export_restore_keeps_observations_and_context(self) -> None:
        self.runtime.process(
            AdapterEnvelope(
                "state",
                "sensor.device_area",
                {"state": "Alpha Room"},
                at(0),
                at(0),
            )
        )
        saved = self.runtime.export_state()
        restored = PresenceRuntime(integration_config(), now=lambda: at(11))

        restored.restore_state(saved)

        self.assertEqual(restored.snapshot.count_minimum, 1)
        self.assertEqual(restored.snapshot.presences[0].location.level.value, "home")
        self.assertIsNone(restored.snapshot.presences[0].location.area)
        self.assertEqual(restored.snapshot.devices[0].location.area, "alpha")

    def test_export_restore_keeps_last_confirmed_image(self) -> None:
        self.runtime.process(
            AdapterEnvelope(
                "mqtt",
                "frigate/events",
                {
                    "type": "update",
                    "after": {
                        "id": "event-image",
                        "camera": "camera_a",
                        "label": "person",
                        "start_time": at(0).timestamp(),
                        "frame_time": at(1).timestamp(),
                        "end_time": None,
                        "current_zones": ["zone_alpha"],
                    },
                },
                at(1),
                at(1),
            )
        )
        self.runtime.process(
            AdapterEnvelope(
                "mqtt",
                "frigate/tracked_object_update",
                {
                    "type": "face",
                    "id": "event-image",
                    "camera": "camera_a",
                    "name": "person_a",
                    "score": 0.95,
                    "timestamp": at(2).timestamp(),
                },
                at(2),
                at(2),
            )
        )
        restored = PresenceRuntime(integration_config(), now=lambda: at(11))

        restored.restore_state(self.runtime.export_state())

        record = restored.latest_images["person_a"]
        self.assertEqual(record.detection_id, "event-image")
        self.assertEqual(record.image.reference, "frigate:event:event-image")
        self.assertEqual(restored.detection("event-image").revision, 2)

    def test_late_ptz_history_revises_cached_event_geometry(self) -> None:
        runtime = PresenceRuntime(integration_config(), now=lambda: at(10))
        event = AdapterEnvelope(
            "mqtt",
            "frigate/events",
            {
                "type": "update",
                "after": {
                    "id": "event-late-context",
                    "camera": "camera_a",
                    "label": "person",
                    "start_time": at(0).timestamp(),
                    "frame_time": at(1).timestamp(),
                    "end_time": None,
                    "current_zones": [],
                },
            },
            at(1),
            at(1),
        )

        initial = runtime.process(event)
        runtime.process(
            AdapterEnvelope(
                "state",
                "select.camera_profile",
                {"state": "profile_alpha"},
                at(-1),
                at(2),
            )
        )
        revised = runtime.process(
            AdapterEnvelope(
                "state",
                "sensor.camera_motion_state",
                {"state": "Available"},
                at(0),
                at(3),
            )
        )

        self.assertEqual(initial.detections[0].location.level.value, "floor")
        self.assertEqual(revised.detections[0].location.area, "alpha")
        self.assertEqual(revised.detections[0].location.method, "ptz_profile_fallback")
        self.assertEqual(revised.detections[0].detected_at, at(0))

    def test_restore_does_not_resurrect_removed_source(self) -> None:
        self.runtime.process(
            AdapterEnvelope(
                "state",
                "sensor.device_area",
                {"state": "Alpha Room"},
                at(0),
                at(0),
            )
        )
        saved = self.runtime.export_state()
        raw = {
            "schema_version": 1,
            "areas": {"alpha": "floor_alpha", "beta": "floor_alpha"},
            "adjacency": {"alpha": ["beta"], "beta": ["alpha"]},
            "identities": {},
            "cameras": {},
            "sources": [],
        }
        from presence_engine.configuration import parse_configuration

        restored = PresenceRuntime(parse_configuration(raw), now=lambda: at(11))

        restored.restore_state(saved)

        self.assertEqual(restored.snapshot.count_maximum, 0)
        self.assertFalse(restored.snapshot.coverage_degraded)
        self.assertNotIn("device_area", restored.snapshot.unavailable_source_ids)

    def test_tracked_endpoint_unavailable_is_absence_not_degraded_coverage(self) -> None:
        self.runtime.process(
            AdapterEnvelope(
                "state",
                "sensor.device_area",
                {"state": "Alpha Room"},
                at(0),
                at(0),
            )
        )
        update = self.runtime.process(
            AdapterEnvelope(
                "state",
                "sensor.device_area",
                {"state": "unavailable"},
                at(1),
                at(1),
            )
        )
        self.assertEqual(update.snapshot.count_maximum, 0)
        self.assertFalse(update.snapshot.coverage_degraded)
        saved = self.runtime.export_state()
        saved["unavailable_sources"] = ["device_area", "removed_source"]
        restored = PresenceRuntime(integration_config(), now=lambda: at(11))

        restored.restore_state(saved)

        self.assertEqual(restored.snapshot.count_maximum, 0)
        self.assertFalse(restored.snapshot.coverage_degraded)
        self.assertNotIn("device_area", restored.snapshot.unavailable_source_ids)
        self.assertNotIn("removed_source", restored.snapshot.unavailable_source_ids)

    def test_missing_infrastructure_source_degrades_coverage(self) -> None:
        update = self.runtime.mark_channel_unavailable(("area_count",))

        self.assertTrue(update.snapshot.coverage_degraded)
        self.assertEqual(update.snapshot.unavailable_source_ids, ("area_count",))

    def test_dog_event_is_anonymous_and_ends_with_direct_evidence(self) -> None:
        active = self.runtime.process(
            AdapterEnvelope(
                "mqtt",
                "frigate/events",
                {
                    "type": "update",
                    "after": {
                        "id": "event-dog",
                        "camera": "camera_a",
                        "label": "dog",
                        "start_time": at(0).timestamp(),
                        "frame_time": at(1).timestamp(),
                        "end_time": None,
                        "current_zones": ["zone_alpha"],
                    },
                },
                at(1),
                at(1),
            )
        )

        self.assertEqual((active.snapshot.count_minimum, active.snapshot.count_maximum), (1, 1))
        self.assertIsNone(active.snapshot.presences[0].identity)
        self.assertEqual(active.snapshot.presences[0].classification, "dog")

        ended = self.runtime.process(
            AdapterEnvelope(
                "mqtt",
                "frigate/events",
                {
                    "type": "end",
                    "after": {
                        "id": "event-dog",
                        "camera": "camera_a",
                        "label": "dog",
                        "start_time": at(0).timestamp(),
                        "frame_time": at(3).timestamp(),
                        "end_time": at(3).timestamp(),
                        "current_zones": ["zone_alpha"],
                    },
                },
                at(3),
                at(3),
            )
        )

        self.assertEqual((ended.snapshot.count_minimum, ended.snapshot.count_maximum), (0, 0))
        self.assertEqual(ended.detections[0].classification, "dog")
        self.assertIsNotNone(self.runtime.detection("event-dog"))

    def test_expiration_revises_current_snapshot_without_deleting_history(self) -> None:
        config = integration_config()
        sources = tuple(
            replace(source, expires_after_seconds=5)
            if source.source_id == "area_count"
            else source
            for source in config.sources
        )
        expiring_config = EngineConfiguration(
            schema_version=config.schema_version,
            areas=config.areas,
            adjacency=config.adjacency,
            identities=config.identities,
            cameras=config.cameras,
            sources=sources,
        )
        current = [at(0)]
        runtime = PresenceRuntime(expiring_config, now=lambda: current[0])
        runtime.process(
            AdapterEnvelope(
                "state",
                "sensor.area_count",
                {"state": "1"},
                at(0),
                at(0),
            )
        )
        revision_before = runtime.snapshot.revision

        current[0] = at(6)
        update = runtime.refresh()

        self.assertTrue(update.changed)
        self.assertEqual(update.snapshot.count_maximum, 0)
        self.assertGreater(update.snapshot.revision, revision_before)
        self.assertEqual(runtime.next_expiration(), None)
        self.assertEqual(len(runtime.export_state()["observations"]), 1)

    def test_same_entity_state_and_observation_time_do_not_advance_revision(self) -> None:
        runtime = PresenceRuntime(integration_config(), now=lambda: at(10))
        first = runtime.process(
            AdapterEnvelope(
                "state",
                "sensor.device_area",
                {"state": "alpha"},
                at(0),
                at(1),
            )
        )
        second = runtime.process(
            AdapterEnvelope(
                "state",
                "sensor.device_area",
                {"state": "alpha", "attributes": {"diagnostic": 2}},
                at(0),
                at(2),
            )
        )

        self.assertFalse(second.changed)
        self.assertEqual(second.snapshot.revision, first.snapshot.revision)

    def test_frigate_target_and_mtr_population_share_one_runtime_result(self) -> None:
        configuration = parse_configuration(
            {
                "schema_version": 1,
                "areas": {"alpha": "floor_alpha", "beta": "floor_alpha"},
                "adjacency": {"alpha": ["beta"], "beta": ["alpha"]},
                "cameras": {
                    "camera_a": {
                        "floor": "floor_alpha",
                        "zone_to_area": {"zone_alpha": "alpha"},
                    }
                },
                "sources": [
                    {
                        "source_id": "frigate_events",
                        "adapter": "frigate_events",
                        "topics": ["frigate/events"],
                        "options": {"labels": ["person"]},
                    },
                    {
                        "source_id": "mtr",
                        "adapter": "mtr_count",
                        "entity_ids": ["sensor.total", "sensor.zone_1", "sensor.zone_2"],
                        "floor": "floor_alpha",
                        "options": {
                            "total_entity_id": "sensor.total",
                            "zone_areas": {
                                "sensor.zone_1": "alpha",
                                "sensor.zone_2": "beta",
                            },
                        },
                    },
                ],
            }
        )
        runtime = PresenceRuntime(configuration, now=lambda: at(10))
        for entity_id, value, second in (
            ("sensor.zone_1", "1", 0),
            ("sensor.zone_2", "0", 1),
            ("sensor.total", "1", 2),
        ):
            runtime.process(
                AdapterEnvelope("state", entity_id, {"state": value}, at(second), at(second))
            )

        update = runtime.process(
            AdapterEnvelope(
                "mqtt",
                "frigate/events",
                {
                    "type": "update",
                    "after": {
                        "id": "event-shared-population",
                        "camera": "camera_a",
                        "label": "person",
                        "start_time": at(3).timestamp(),
                        "frame_time": at(3).timestamp(),
                        "end_time": None,
                        "current_zones": ["zone_alpha"],
                    },
                },
                at(3),
                at(3),
            )
        )

        self.assertEqual((update.snapshot.count_minimum, update.snapshot.count_maximum), (1, 1))
        self.assertEqual(update.snapshot.presences[0].location.area, "alpha")

    def test_compound_source_recovers_only_after_every_channel_is_fresh(self) -> None:
        configuration = parse_configuration(
            {
                "schema_version": 1,
                "areas": {"alpha": "floor_alpha", "beta": "floor_alpha"},
                "adjacency": {"alpha": ["beta"], "beta": ["alpha"]},
                "cameras": {},
                "sources": [
                    {
                        "source_id": "mtr",
                        "adapter": "mtr_count",
                        "entity_ids": ["sensor.total", "sensor.zone_1", "sensor.zone_2"],
                        "floor": "floor_alpha",
                        "options": {
                            "total_entity_id": "sensor.total",
                            "zone_areas": {
                                "sensor.zone_1": "alpha",
                                "sensor.zone_2": "beta",
                            },
                        },
                    }
                ],
            }
        )
        runtime = PresenceRuntime(configuration, now=lambda: at(20))
        initial_partial = runtime.process(
            AdapterEnvelope("state", "sensor.zone_1", {"state": "1"}, at(0), at(0))
        )
        self.assertTrue(initial_partial.snapshot.coverage_degraded)

        for entity_id, value, second in (
            ("sensor.zone_2", "0", 1),
            ("sensor.total", "1", 2),
        ):
            healthy = runtime.process(
                AdapterEnvelope("state", entity_id, {"state": value}, at(second), at(second))
            )
        self.assertFalse(healthy.snapshot.coverage_degraded)

        degraded = runtime.process(
            AdapterEnvelope(
                "state",
                "sensor.zone_1",
                {"state": "unavailable"},
                at(3),
                at(3),
            )
        )
        self.assertTrue(degraded.snapshot.coverage_degraded)
        self.assertEqual(degraded.snapshot.count_maximum, 0)

        partial = runtime.process(
            AdapterEnvelope("state", "sensor.total", {"state": "1"}, at(4), at(4))
        )
        self.assertTrue(partial.snapshot.coverage_degraded)
        self.assertEqual(partial.snapshot.count_maximum, 0)

        recovered = runtime.process(
            AdapterEnvelope("state", "sensor.zone_1", {"state": "1"}, at(5), at(5))
        )
        self.assertFalse(recovered.snapshot.coverage_degraded)
        self.assertEqual(recovered.snapshot.count_minimum, 1)

    def test_unavailable_camera_gates_only_its_evidence_until_recovery(self) -> None:
        configuration = parse_configuration(
            {
                "schema_version": 1,
                "areas": {"alpha": "floor_alpha", "beta": "floor_alpha"},
                "adjacency": {"alpha": ["beta"], "beta": ["alpha"]},
                "cameras": {
                    "camera_a": {
                        "floor": "floor_alpha",
                        "fixed_area": "alpha",
                        "availability_entity_ids": [
                            "camera.camera_a",
                            "binary_sensor.camera_a_connected",
                        ],
                    },
                    "camera_b": {
                        "floor": "floor_alpha",
                        "fixed_area": "beta",
                        "availability_entity_ids": ["camera.camera_b"],
                    },
                },
                "sources": [
                    {
                        "source_id": "frigate_events",
                        "adapter": "frigate_events",
                        "topics": ["frigate/events"],
                        "options": {"labels": ["person"]},
                    }
                ],
            }
        )
        runtime = PresenceRuntime(configuration, now=lambda: at(20))
        for entity_id, state in (
            ("camera.camera_a", "idle"),
            ("binary_sensor.camera_a_connected", "on"),
            ("camera.camera_b", "idle"),
        ):
            runtime.process(
                AdapterEnvelope(
                    "state",
                    entity_id,
                    {"state": state},
                    at(0),
                    at(0),
                )
            )

        def event(event_id: str, camera_id: str, second: int) -> AdapterEnvelope:
            return AdapterEnvelope(
                "mqtt",
                "frigate/events",
                {
                    "type": "update",
                    "after": {
                        "id": event_id,
                        "camera": camera_id,
                        "label": "person",
                        "start_time": at(second).timestamp(),
                        "frame_time": at(second).timestamp(),
                        "end_time": None,
                        "current_zones": [],
                    },
                },
                at(second),
                at(second),
            )

        runtime.process(event("event-a", "camera_a", 1))
        runtime.process(event("event-b", "camera_b", 2))
        degraded = runtime.process(
            AdapterEnvelope(
                "state",
                "binary_sensor.camera_a_connected",
                {"state": "off"},
                at(3),
                at(3),
            )
        )

        self.assertTrue(degraded.snapshot.coverage_degraded)
        self.assertEqual(
            degraded.snapshot.unavailable_source_ids,
            ("camera:camera_a",),
        )
        self.assertEqual(degraded.snapshot.count_minimum, 1)
        self.assertEqual(degraded.snapshot.presences[0].location.area, "beta")

        ignored = runtime.process(event("event-a-while-down", "camera_a", 4))
        self.assertEqual(ignored.snapshot.count_minimum, 1)
        self.assertIsNone(runtime.detection("event-a-while-down"))

        still_degraded = runtime.process(
            AdapterEnvelope(
                "state",
                "camera.camera_a",
                {"state": "unavailable"},
                at(5),
                at(5),
            )
        )
        still_degraded = runtime.process(
            AdapterEnvelope(
                "state",
                "camera.camera_a",
                {"state": "idle"},
                at(6),
                at(6),
            )
        )
        self.assertTrue(still_degraded.snapshot.coverage_degraded)
        self.assertEqual(still_degraded.snapshot.count_minimum, 1)

        recovered = runtime.process(
            AdapterEnvelope(
                "state",
                "binary_sensor.camera_a_connected",
                {"state": "on"},
                at(7),
                at(7),
            )
        )
        self.assertFalse(recovered.snapshot.coverage_degraded)

        accepted = runtime.process(event("event-a-after-recovery", "camera_a", 8))
        self.assertEqual(accepted.snapshot.count_minimum, 2)


if __name__ == "__main__":
    unittest.main()
