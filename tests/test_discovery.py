from __future__ import annotations

import unittest

from presence_engine.configuration import AdapterType, SourceDefinition
from presence_engine.discovery import (
    EntityDescriptor,
    apply_discovery,
    discover_candidate,
    reconcile_entity_bindings,
    resolve_raw_registry_bindings,
)

from integration_helpers import integration_config


class DiscoveryTests(unittest.TestCase):
    def test_known_radar_with_registry_area_is_ready(self) -> None:
        candidate = discover_candidate(
            EntityDescriptor(
                registry_id="entry-radar",
                entity_id="binary_sensor.office_radar",
                platform="esphome",
                unique_id="office_ld2450_presence",
                domain="binary_sensor",
                area_id="office",
                device_model="MSR-2",
            )
        )

        self.assertIsNotNone(candidate)
        assert candidate is not None
        self.assertEqual(candidate.adapter, AdapterType.BINARY_PRESENCE)
        self.assertTrue(candidate.ready)
        self.assertEqual(candidate.suggested_area, "office")

    def test_mtr_zone_is_pending_instead_of_guessing_device_area(self) -> None:
        candidate = discover_candidate(
            EntityDescriptor(
                registry_id="entry-zone",
                entity_id="sensor.kitchen_zone_3_all_target_count",
                platform="esphome",
                unique_id="kitchen_mtr_zone_3_all_target_count",
                domain="sensor",
                area_id="kitchen",
                device_model="MTR-1",
            )
        )

        self.assertIsNotNone(candidate)
        assert candidate is not None
        self.assertFalse(candidate.ready)
        self.assertIsNone(candidate.suggested_area)
        self.assertIn("physical_area", candidate.missing_configuration)

    def test_unknown_sensor_is_not_given_invented_semantics(self) -> None:
        candidate = discover_candidate(
            EntityDescriptor(
                registry_id="entry-unknown",
                entity_id="sensor.office_misc",
                platform="example",
                unique_id="misc",
                domain="sensor",
                area_id="office",
            )
        )

        self.assertIsNone(candidate)

    def test_registry_id_reconciles_entity_rename(self) -> None:
        result = reconcile_entity_bindings(
            {"entry-radar": "binary_sensor.old_office_radar", "removed": "sensor.old"},
            (
                EntityDescriptor(
                    registry_id="entry-radar",
                    entity_id="binary_sensor.office_radar",
                    platform="esphome",
                    unique_id="office_ld2450_presence",
                    domain="binary_sensor",
                ),
            ),
        )

        self.assertEqual(
            result.renamed["entry-radar"],
            ("binary_sensor.old_office_radar", "binary_sensor.office_radar"),
        )
        self.assertEqual(result.missing_registry_ids, ("removed",))

    def test_ready_known_family_is_added_but_ambiguous_mtr_is_pending(self) -> None:
        descriptors = (
            EntityDescriptor(
                registry_id="entry-radar",
                entity_id="binary_sensor.gamma_radar",
                platform="esphome",
                unique_id="gamma_msr2_ld2450_presence",
                domain="binary_sensor",
                area_id="gamma",
                device_model="MSR-2",
            ),
            EntityDescriptor(
                registry_id="entry-zone",
                entity_id="sensor.gamma_zone_1_all_target_count",
                platform="esphome",
                unique_id="gamma_mtr_zone_1_all_target_count",
                domain="sensor",
                area_id="gamma",
                device_model="MTR-1",
            ),
        )

        plan = apply_discovery(integration_config(), descriptors)

        self.assertEqual(len(plan.activated), 1)
        self.assertEqual(len(plan.pending), 1)
        self.assertIn("binary_sensor.gamma_radar", plan.configuration.entity_ids)
        self.assertNotIn("sensor.gamma_zone_1_all_target_count", plan.configuration.entity_ids)

    def test_explicit_device_suppresses_auto_discovered_auxiliary_channels(self) -> None:
        configured = integration_config()
        configured = type(configured)(
            schema_version=configured.schema_version,
            areas=configured.areas,
            adjacency=configured.adjacency,
            identities=configured.identities,
            cameras=configured.cameras,
            sources=(
                *configured.sources,
                SourceDefinition(
                    source_id="office_radar",
                    adapter=AdapterType.BINARY_PRESENCE,
                    entity_ids=("binary_sensor.office_radar_target",),
                    entity_registry_ids=("entry-radar-target",),
                    area="alpha",
                ),
            ),
        )
        descriptors = (
            EntityDescriptor(
                registry_id="entry-radar-target",
                entity_id="binary_sensor.office_radar_target",
                platform="esphome",
                unique_id="office_ld2450_radar_target",
                domain="binary_sensor",
                area_id="alpha",
                device_model="MSR-2",
                device_id="device-office-radar",
            ),
            EntityDescriptor(
                registry_id="entry-radar-moving",
                entity_id="binary_sensor.office_radar_moving_target",
                platform="esphome",
                unique_id="office_ld2450_radar_moving_target",
                domain="binary_sensor",
                area_id="alpha",
                device_model="MSR-2",
                device_id="device-office-radar",
            ),
        )

        plan = apply_discovery(configured, descriptors)

        self.assertEqual(plan.activated, ())
        self.assertNotIn(
            "binary_sensor.office_radar_moving_target",
            plan.configuration.entity_ids,
        )

    def test_raw_registry_binding_survives_rename(self) -> None:
        raw = {
            "sources": [
                {
                    "entity_ids": ["binary_sensor.old_name"],
                    "entity_registry_ids": ["entry-radar"],
                }
            ],
            "cameras": {
                "camera_a": {
                    "profile_entity_id": "select.old_profile",
                    "profile_registry_id": "entry-profile",
                    "availability_entity_ids": ["camera.old_camera"],
                    "availability_registry_ids": ["entry-camera"],
                }
            },
        }
        descriptors = (
            EntityDescriptor(
                "entry-radar",
                "binary_sensor.new_name",
                "esphome",
                "radar",
                "binary_sensor",
            ),
            EntityDescriptor(
                "entry-profile",
                "select.new_profile",
                "frigate",
                "profile",
                "select",
            ),
            EntityDescriptor(
                "entry-camera",
                "camera.new_camera",
                "frigate",
                "camera",
                "camera",
            ),
        )

        resolved = resolve_raw_registry_bindings(raw, descriptors)

        self.assertEqual(
            resolved["sources"][0]["entity_ids"],
            ["binary_sensor.new_name"],
        )
        self.assertEqual(
            resolved["cameras"]["camera_a"]["profile_entity_id"],
            "select.new_profile",
        )
        self.assertEqual(
            resolved["cameras"]["camera_a"]["availability_entity_ids"],
            ["camera.new_camera"],
        )


if __name__ == "__main__":
    unittest.main()
