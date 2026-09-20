from __future__ import annotations

import unittest

from presence_engine.configuration import (
    AvailabilityRole,
    ConfigurationError,
    parse_configuration,
)

from integration_helpers import integration_config


class ConfigurationTests(unittest.TestCase):
    def test_collects_only_exact_configured_subscriptions(self) -> None:
        config = integration_config()

        self.assertEqual(
            config.topics,
            ("frigate/events", "frigate/tracked_object_update"),
        )
        self.assertEqual(
            config.entity_ids,
            (
                "select.camera_preset",
                "select.camera_profile",
                "sensor.area_count",
                "sensor.camera_motion_state",
                "sensor.device_area",
            ),
        )

    def test_rejects_an_engine_output_as_input(self) -> None:
        raw = {
            "schema_version": 1,
            "areas": {"alpha": "floor_alpha"},
            "adjacency": {"alpha": []},
            "sources": [
                {
                    "source_id": "feedback",
                    "adapter": "count",
                    "entity_ids": ["sensor.presence_engine_snapshot"],
                    "area": "alpha",
                }
            ],
        }

        with self.assertRaises(ConfigurationError):
            parse_configuration(raw)

    def test_rejects_unknown_area_in_camera_geometry(self) -> None:
        raw = {
            "schema_version": 1,
            "areas": {"alpha": "floor_alpha"},
            "adjacency": {"alpha": []},
            "cameras": {
                "camera_a": {
                    "floor": "floor_alpha",
                    "zone_to_area": {"zone": "missing"},
                }
            },
        }

        with self.assertRaises(ConfigurationError):
            parse_configuration(raw)

    def test_camera_availability_entities_are_exact_subscriptions(self) -> None:
        raw = {
            "schema_version": 1,
            "areas": {"alpha": "floor_alpha"},
            "adjacency": {"alpha": []},
            "cameras": {
                "camera_a": {
                    "floor": "floor_alpha",
                    "availability_entity_ids": [
                        "camera.camera_a",
                        "binary_sensor.camera_a_connected",
                    ],
                    "availability_registry_ids": ["camera-entry", "connected-entry"],
                }
            },
        }

        config = parse_configuration(raw)

        self.assertEqual(
            config.entity_ids,
            ("binary_sensor.camera_a_connected", "camera.camera_a"),
        )

    def test_camera_availability_registry_ids_must_be_paired(self) -> None:
        raw = {
            "schema_version": 1,
            "areas": {},
            "adjacency": {},
            "cameras": {
                "camera_a": {
                    "floor": "floor_alpha",
                    "availability_entity_ids": ["camera.camera_a"],
                    "availability_registry_ids": ["one", "two"],
                }
            },
        }

        with self.assertRaises(ConfigurationError):
            parse_configuration(raw)

    def test_camera_availability_pairs_reject_duplicates(self) -> None:
        raw = {
            "schema_version": 1,
            "areas": {},
            "adjacency": {},
            "cameras": {
                "camera_a": {
                    "floor": "floor_alpha",
                    "availability_entity_ids": [
                        "camera.camera_a",
                        "camera.camera_a",
                    ],
                    "availability_registry_ids": ["one", "two"],
                }
            },
        }

        with self.assertRaises(ConfigurationError):
            parse_configuration(raw)

    def test_rejects_non_positive_source_expiration(self) -> None:
        raw = {
            "schema_version": 1,
            "areas": {"alpha": "floor_alpha"},
            "adjacency": {"alpha": []},
            "sources": [
                {
                    "source_id": "area_count",
                    "adapter": "count",
                    "entity_ids": ["sensor.area_count"],
                    "area": "alpha",
                    "expires_after_seconds": 0,
                }
            ],
        }

        with self.assertRaises(ConfigurationError):
            parse_configuration(raw)

    def test_rejects_unknown_mtr_zone_area(self) -> None:
        raw = {
            "schema_version": 1,
            "areas": {"alpha": "floor_alpha"},
            "adjacency": {"alpha": []},
            "sources": [
                {
                    "source_id": "mtr",
                    "adapter": "mtr_count",
                    "entity_ids": ["sensor.total", "sensor.zone_1"],
                    "floor": "floor_alpha",
                    "options": {
                        "total_entity_id": "sensor.total",
                        "zone_areas": {"sensor.zone_1": "missing"},
                    },
                }
            ],
        }

        with self.assertRaises(ConfigurationError):
            parse_configuration(raw)

    def test_rejects_non_list_person_source_filters(self) -> None:
        raw = {
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
                        "ignored_source_prefixes": "device_tracker.indoor_"
                    },
                }
            ],
        }

        with self.assertRaises(ConfigurationError):
            parse_configuration(raw)

    def test_tracked_endpoints_do_not_degrade_coverage_by_default(self) -> None:
        config = integration_config()

        device = next(source for source in config.sources if source.source_id == "device_area")
        counter = next(source for source in config.sources if source.source_id == "area_count")

        self.assertFalse(device.degrades_coverage_when_unavailable)
        self.assertTrue(counter.degrades_coverage_when_unavailable)

    def test_availability_role_can_override_the_adapter_default(self) -> None:
        raw = {
            "schema_version": 1,
            "areas": {"alpha": "floor_alpha"},
            "adjacency": {"alpha": []},
            "sources": [
                {
                    "source_id": "scanner_health",
                    "adapter": "binary_presence",
                    "entity_ids": ["binary_sensor.scanner_health"],
                    "area": "alpha",
                    "availability_role": "observation",
                },
                {
                    "source_id": "tracked_endpoint",
                    "adapter": "bermuda_area",
                    "entity_ids": ["sensor.tracked_endpoint_area"],
                    "availability_role": "coverage",
                },
            ],
        }

        config = parse_configuration(raw)

        self.assertEqual(config.sources[0].availability_role, AvailabilityRole.OBSERVATION)
        self.assertFalse(config.sources[0].degrades_coverage_when_unavailable)
        self.assertTrue(config.sources[1].degrades_coverage_when_unavailable)

    def test_source_health_requires_one_entity_and_unambiguous_states(self) -> None:
        base = {
            "schema_version": 1,
            "areas": {},
            "adjacency": {},
        }
        for source in (
            {
                "source_id": "scanner_health",
                "adapter": "source_health",
                "entity_ids": ["binary_sensor.scanner_a", "binary_sensor.scanner_b"],
            },
            {
                "source_id": "scanner_health",
                "adapter": "source_health",
                "entity_ids": ["binary_sensor.scanner_a"],
                "options": {
                    "healthy_states": ["on"],
                    "unhealthy_states": ["off"],
                },
            },
        ):
            with self.subTest(source=source):
                with self.assertRaises(ConfigurationError):
                    parse_configuration({**base, "sources": [source]})

    def test_source_health_is_coverage_by_default(self) -> None:
        config = parse_configuration(
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
        )

        self.assertTrue(config.sources[0].degrades_coverage_when_unavailable)


if __name__ == "__main__":
    unittest.main()
