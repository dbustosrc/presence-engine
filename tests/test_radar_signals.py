from copy import deepcopy
import unittest

from helpers import at
from presence_engine.adapters import AdapterEnvelope
from presence_engine.configuration import ConfigurationError, parse_configuration
from presence_engine.discovery import EntityDescriptor, resolve_raw_registry_bindings
from presence_engine.runtime import PresenceRuntime


def configuration(limit=3, seconds=20):
    return {"schema_version": 1, "areas": {"alpha": "ground"}, "cameras": {}, "sources": [{
        "source_id": "radar_a", "adapter": "binary_presence", "area": "alpha", "floor": "ground",
        "entity_ids": ["binary_sensor.body", "sensor.x", "sensor.y", "sensor.speed", "sensor.range"],
        "options": {"history_limit": limit, "history_seconds": seconds,
            "radar_channels": {"sensor.x": {"target_slot": "slot_1", "metric": "x"},
                "sensor.y": {"target_slot": "slot_1", "metric": "y"},
                "sensor.speed": {"target_slot": "slot_1", "metric": "speed"},
                "sensor.range": {"target_slot": "aggregate", "metric": "distance"}}}}]}


class RadarSignalTests(unittest.TestCase):
    def setUp(self):
        self.second = 0
        self.raw = configuration()
        self.runtime = PresenceRuntime(parse_configuration(self.raw), now=lambda: at(self.second))

    def deliver(self, entity, value, second, unit="mm", observed=None, extra=None):
        self.second = second
        return self.runtime.process(AdapterEnvelope("state", entity,
            {"state": str(value), "attributes": {"unit_of_measurement": unit, **(extra or {})},
             "last_updated": at(second if observed is None else observed).isoformat()},
            at(0), at(second)))

    def test_geometry_neither_creates_presence_nor_changes_an_existing_body(self):
        initial = self.runtime.snapshot
        update = self.deliver("sensor.x", -150, 1)
        self.assertEqual(update.snapshot, initial)
        self.assertFalse(update.changed)
        self.deliver("binary_sensor.body", "on", 2)
        body = self.runtime.snapshot
        for entity, value, unit in (("sensor.y", 0, "mm"), ("sensor.speed", -100, "mm/s"),
                                    ("sensor.range", 0, "cm"), ("sensor.x", "unavailable", "mm")):
            update = self.deliver(entity, value, self.second + 1, unit)
            self.assertEqual(update.snapshot, body)
            self.assertFalse(update.changed)
            self.assertFalse(update.detections)
        self.assertEqual(body.count_minimum, 1)

    def test_unknown_invalid_units_and_signed_coordinates_are_not_absence(self):
        cases = [("sensor.x", -2, "cm", "valid"), ("sensor.y", 0, "mm", "valid"),
                 ("sensor.speed", -2, "m/s", "valid"), ("sensor.range", -2, "mm", "invalid_value"),
                 ("sensor.x", "nan", "mm", "invalid_value"), ("sensor.x", "inf", "mm", "invalid_value"),
                 ("sensor.x", 2, "", "invalid_unit"), ("sensor.speed", 2, "mm", "invalid_unit"),
                 ("sensor.x", "unknown", "mm", "unknown"), ("sensor.x", "unavailable", "mm", "unavailable")]
        for entity, value, unit, status in cases:
            self.deliver(entity, value, self.second + 1, unit)
            item = next(p for p in self.runtime.radar_history_payload() if p["entity_id"] == entity)
            self.assertEqual(item["status"], status)
            self.assertEqual(item["unit"], unit)
            self.assertEqual(item["latest_value"], value if status == "valid" else None)
        self.assertFalse(self.runtime.failures)

    def test_channels_keep_separate_clocks_and_duplicates_do_not_refresh(self):
        self.deliver("sensor.x", 1, 1)
        self.deliver("sensor.y", 3, 2)
        self.deliver("sensor.x", 2, 3, observed=.5)
        self.deliver("sensor.x", 1, 4, extra={"friendly_name": "New label"})
        by_entity = {p["entity_id"]: p for p in self.runtime.radar_history_payload(include_samples=True)}
        self.assertEqual(by_entity["sensor.x"]["observed_at"], at(1).isoformat())
        self.assertEqual(by_entity["sensor.y"]["observed_at"], at(2).isoformat())
        self.assertEqual(by_entity["sensor.x"]["sample_count"], 1)
        self.assertEqual(by_entity["sensor.x"]["clock_basis"], "ha_state_update")
        self.deliver("binary_sensor.body", "on", 5)
        body = self.runtime.snapshot
        self.deliver("sensor.x", 20, 6, observed=7)
        self.assertEqual(self.runtime.snapshot, body)
        self.assertEqual(self.runtime.failures[0].error_type, "ValueError")

    def test_retention_restart_corruption_and_rebinding_do_not_resurrect(self):
        self.raw = configuration(limit=3.0, seconds=20.0)
        self.runtime = PresenceRuntime(parse_configuration(self.raw), now=lambda: at(self.second))
        for second in range(1, 6):
            self.deliver("sensor.x", second, second)
        saved = self.runtime.export_state()
        self.assertEqual(len(saved["radar_signals"]), 3)
        self.assertTrue(self.runtime.radar_history_payload()[2]["truncated"])
        saved["radar_signals"].append({"corrupt": True})
        self.runtime = PresenceRuntime(parse_configuration(self.raw), now=lambda: at(self.second))
        self.runtime.restore_state(saved)
        self.assertEqual(self.runtime.radar_history_payload()[2]["observed_at"], at(5).isoformat())
        self.second = 25
        saved = self.runtime.export_state()
        self.runtime = PresenceRuntime(parse_configuration(self.raw), now=lambda: at(self.second))
        self.runtime.restore_state(saved)
        self.deliver("sensor.x", 5, 26)
        self.assertEqual(self.runtime.radar_history_payload()[2]["status"], "no_recent_samples")
        changed = deepcopy(self.raw)
        changed["sources"][0]["dependency_group"] = "another_sensor"
        self.runtime = PresenceRuntime(parse_configuration(changed), now=lambda: at(self.second))
        self.runtime.restore_state(saved)
        self.assertTrue(all(p["sample_count"] == 0 for p in self.runtime.radar_history_payload()))

    def test_shared_ble_radar_budget_and_independent_target_slots(self):
        raw = deepcopy(self.raw)
        raw["sources"][0]["options"]["radar_channels"]["sensor.y"]["target_slot"] = "slot_2"
        raw["sources"].append({"source_id": "radio", "adapter": "bermuda_signal", "entity_ids": ["sensor.radio"],
            "options": {"device_id": "phone", "receiver_id": "receiver", "metric": "distance"}})
        self.runtime = PresenceRuntime(parse_configuration(raw), now=lambda: at(self.second), max_records=3)
        for second in range(1, 9):
            self.deliver("sensor.radio" if second % 2 else "sensor.x", second, second, "m")
        saved = self.runtime.export_state()
        self.assertEqual(len(saved["device_signals"]) + len(saved["radar_signals"]), 3)
        self.assertEqual({p["target_slot"] for p in self.runtime.radar_history_payload()}, {"slot_1", "slot_2", "aggregate"})
        self.assertTrue(self.runtime.radar_history_payload()[2]["truncated"])

    def test_mtr_counts_do_not_wait_for_or_sum_telemetry(self):
        raw = configuration()
        source = raw["sources"][0]
        source.update(adapter="mtr_count", entity_ids=["sensor.total", "sensor.zone", "sensor.x"])
        source["options"]["radar_channels"] = {"sensor.x": {"target_slot": "slot_1", "metric": "x"}}
        source["options"].update(total_entity_id="sensor.total", zone_areas={"sensor.zone": "alpha"})
        self.runtime = PresenceRuntime(parse_configuration(raw), now=lambda: at(self.second))
        self.deliver("sensor.total", 1, 1)
        self.deliver("sensor.zone", 1, 2)
        self.assertEqual(self.runtime.snapshot.count_minimum, 1)
        initial = self.runtime.snapshot
        self.deliver("sensor.x", 5000, 3)
        self.assertEqual(self.runtime.snapshot, initial)

    def test_validation_rejects_ambiguous_bindings_and_unsupported_channels(self):
        for modification in (lambda s: s.update(adapter="bermuda_area"),
                             lambda s: s["options"]["radar_channels"].update({"sensor.other": {"target_slot": "slot_1", "metric": "x"}}),
                             lambda s: s["options"]["radar_channels"]["sensor.x"].update(metric="latitude"),
                             lambda s: s["options"]["radar_channels"]["sensor.x"].update(target_slot=""),
                             lambda s: s["options"].update(history_limit=True),
                             lambda s: s["options"].update(history_seconds=float("inf")),
                             lambda s: s["options"]["radar_channels"]["sensor.y"].update(metric="x")):
            raw = deepcopy(self.raw)
            modification(raw["sources"][0])
            with self.assertRaises(ConfigurationError):
                parse_configuration(raw)

    def test_registry_rename_updates_telemetry_count_and_zone_bindings(self):
        raw = {"sources": [{"entity_ids": ["sensor.total", "sensor.zone", "sensor.x"],
            "entity_registry_ids": ["total-id", "zone-id", "x-id"], "options": {
                "total_entity_id": "sensor.total", "zone_areas": {"sensor.zone": "alpha"},
                "radar_channels": {"sensor.x": {"target_slot": "slot_1", "metric": "x"}}}}]}
        descriptors = [EntityDescriptor(rid, entity, "esphome", rid, "sensor") for rid, entity in
            (("total-id", "sensor.total_new"), ("zone-id", "sensor.zone_new"), ("x-id", "sensor.x_new"))]
        updated = resolve_raw_registry_bindings(raw, descriptors)["sources"][0]
        self.assertEqual(updated["options"]["total_entity_id"], "sensor.total_new")
        self.assertEqual(updated["options"]["zone_areas"], {"sensor.zone_new": "alpha"})
        self.assertIn("sensor.x_new", updated["options"]["radar_channels"])
        self.assertIn("sensor.x", raw["sources"][0]["options"]["radar_channels"])
