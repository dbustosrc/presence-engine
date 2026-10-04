"""Radio handoffs are probable body associations, not new identities."""

from dataclasses import replace
import unittest

from presence_engine.adapters import AdapterEnvelope
from presence_engine.configuration import parse_configuration
from presence_engine.engine import CountClaim, ObservationStatus, Quality, RevisionStamp
from presence_engine.runtime import PresenceRuntime
from helpers import at, area, identity, observation


def configuration():
    raw = {"schema_version": 1, "areas": {"alpha": "ground", "beta": "upper"}, "sources": [
        {"source_id": "home", "adapter": "person_home", "entity_ids": ["person.owner"], "identity": "person_a"},
        {"source_id": "phone", "adapter": "bermuda_area", "entity_ids": ["sensor.phone"], "identity": "person_a",
         "options": {"target_id": "phone_a", "area_map": {"Alpha": "alpha", "Beta": "beta"}}},
        *({"source_id": f"radar_{name}", "adapter": "binary_presence", "entity_ids": [f"binary_sensor.{name}"],
           "area": name, "spatial_quality": "high"} for name in ("alpha", "beta")),
        *({"source_id": f"distance_{name}", "adapter": "bermuda_signal", "entity_ids": [f"sensor.distance_{name}"],
           "area": name, "identity": "person_a", "options": {"device_id": "phone_a", "receiver_id": name,
               "metric": "distance"}} for name in ("alpha", "beta"))]}
    return parse_configuration(raw)


class DeviceAssociationTests(unittest.TestCase):
    def setUp(self):
        self.second = 0
        self.runtime = PresenceRuntime(configuration(), now=lambda: at(self.second))

    def deliver(self, channel, state, second, unit="m"):
        self.second = second
        return self.runtime.process(AdapterEnvelope("state", channel,
            {"state": str(state), "attributes": {"unit_of_measurement": unit}}, at(second), at(second)))

    def body(self, area_name, second, active=True, owner="person_a"):
        self.second = second
        item = observation("face", identity_claim=identity(owner, second), location=area(area_name, second),
            detected=second, received=second, status=ObservationStatus.ACTIVE if active else ObservationStatus.ENDED,
            ended=None if active else second)
        self.runtime._store.upsert(item)
        self.runtime._snapshot = self.runtime._resolve_snapshot()

    def seed(self, end=True):
        self.deliver("sensor.distance_alpha", 1, 0)
        self.deliver("sensor.distance_beta", 5, .1)
        self.deliver("sensor.distance_alpha", 1.2, 1)
        self.deliver("sensor.distance_beta", 5.2, 1.1)
        self.deliver("person.owner", "home", 2)
        self.deliver("sensor.phone", "Alpha", 2.1)
        self.body("alpha", 3)
        self.deliver("binary_sensor.alpha", "on", 4)
        if end:
            self.body("alpha", 5, False)

    def move(self, physical=True, unit="m"):
        self.deliver("sensor.phone", "Beta", 10)
        scale = 100 if unit == "cm" else 1
        self.deliver("sensor.distance_alpha", 5 * scale, 11, unit)
        self.deliver("sensor.distance_beta", 1.2 * scale, 11.1, unit)
        self.deliver("sensor.distance_alpha", 6 * scale, 12, unit)
        update = self.deliver("sensor.distance_beta", 1 * scale, 12.1, unit)
        if physical:
            update = self.deliver("binary_sensor.beta", "on", 13)
        return update

    def owner(self):
        return next(p for p in self.runtime.snapshot.presences if p.identity == "person_a")

    def test_held_origin_does_not_block_corroborated_probable_handoff(self):
        self.seed()
        update = self.move()
        self.assertEqual(self.owner().location.area, "beta")
        self.assertEqual(self.owner().location.quality, Quality.MEDIUM)
        self.assertEqual(self.owner().location_status, "device_carried_probable")
        self.assertEqual(self.owner().location.method, "anchored_device_handoff")
        self.assertEqual(self.owner().identity_observed_at, at(2))
        self.assertEqual(update.detections, ())
        self.assertIn("anchored_device_handoff_with_physical_support", update.snapshot.reasons)
        self.assertTrue(any(a.location.area == "alpha" for a in update.snapshot.area_occupancies))
        self.assertGreater(update.snapshot.count_maximum, update.snapshot.count_minimum)

    def test_ble_only_destination_requires_valid_origin_clear(self):
        self.seed()
        self.deliver("binary_sensor.alpha", "off", 8)
        self.move(physical=False)
        self.assertEqual(self.owner().location.area, "beta")
        self.assertFalse(self.runtime.snapshot.area_occupancies)
        self.setUp(); self.seed()
        self.move(physical=False)
        self.assertNotEqual(self.owner().location.area, "beta")

    def test_probable_owner_and_supporting_aggregate_are_not_extra_individuals(self):
        self.seed()
        update = self.move()
        self.assertEqual((update.snapshot.count_minimum, update.snapshot.count_maximum), (1, 2))
        self.assertEqual(self.owner().location_status, "device_carried_probable")
        self.assertEqual(self.owner().location.quality, Quality.MEDIUM)
        self.assertEqual(self.owner().identity_observed_at, at(2))
        self.assertTrue(any(p.identity is None and p.location.area == "alpha"
                            for p in update.snapshot.presences), "the held origin may contain a visitor")
        self.assertEqual({o.location.area for o in update.snapshot.area_occupancies}, {"alpha", "beta"})
        self.assertEqual(update.detections, ())

    def test_supporting_aggregate_preserves_its_additional_population(self):
        self.seed()
        self.move()
        stored = next(o for o in self.runtime._store.values() if o.source.source_id == "radar_beta")
        self.runtime._store.upsert(replace(stored, count=CountClaim(2, 2, at(14), True, Quality.HIGH),
            location=replace(stored.location, observed_at=at(14)), received_at=at(14),
            revisions={key: RevisionStamp(stamp.sequence + 1, at(14))
                       for key, stamp in stored.revisions.items()}))
        self.second = 14
        self.runtime._snapshot = self.runtime._resolve_snapshot()
        self.assertEqual((self.runtime.snapshot.count_minimum, self.runtime.snapshot.count_maximum), (2, 3))
        self.assertTrue(any(p.identity is None and p.location.area == "beta"
                            for p in self.runtime.snapshot.presences))

    def test_old_destination_not_used_as_handoff_support_keeps_uncertainty(self):
        self.deliver("binary_sensor.beta", "on", 0)
        self.seed()
        self.deliver("binary_sensor.alpha", "off", 8)
        self.deliver("sensor.phone", "Beta", 40)
        for name, value, second in (("alpha", 5, 41), ("beta", 1.2, 41.1),
                                    ("alpha", 6, 42), ("beta", 1, 42.1)):
            self.deliver(f"sensor.distance_{name}", value, second)
        self.assertEqual(self.owner().location_status, "device_carried_probable")
        self.assertNotIn("radar_beta", self.owner().location_source_ids)
        self.assertEqual((self.runtime.snapshot.count_minimum, self.runtime.snapshot.count_maximum), (1, 2))
        self.assertTrue(any(p.identity is None and p.location.area == "beta"
                            for p in self.runtime.snapshot.presences))

    def test_stationary_phone_area_jump_and_overlapping_noise_do_not_transfer(self):
        self.seed()
        self.deliver("sensor.phone", "Beta", 10)
        self.deliver("binary_sensor.beta", "on", 11)
        self.assertNotEqual(self.owner().location.area, "beta")
        for name, value, second in (("alpha", 1.1, 12), ("beta", 5.1, 12.1),
                                    ("alpha", 1.3, 13), ("beta", 4.9, 13.1)):
            self.deliver(f"sensor.distance_{name}", value, second)
        self.assertNotEqual(self.owner().location.area, "beta")
        self.assertGreaterEqual(self.runtime.snapshot.count_maximum, 2)

    def test_current_face_wins_even_if_its_coordinates_have_not_changed(self):
        self.seed(end=False)
        self.move()
        self.assertEqual(self.owner().location.area, "alpha")
        self.assertEqual(self.owner().identity_observed_at, at(3))

    def test_units_are_normalized_and_invalid_signal_breaks_handoff(self):
        self.seed(); self.move(unit="cm")
        self.assertEqual(self.owner().location.area, "beta")
        self.deliver("sensor.distance_beta", "unavailable", 14)
        self.assertNotEqual(self.owner().location.method, "anchored_device_handoff")
        self.deliver("sensor.phone", "Beta", 15)
        self.assertIsNone(self.owner().location.area)

    def test_repeated_radio_does_not_roll_anchor_or_handoff_clocks(self):
        self.seed(); self.move()
        initial = self.owner().location.observed_at
        update = self.deliver("sensor.distance_beta", 1, 14)
        self.assertFalse(update.changed)
        self.assertEqual(self.owner().location.observed_at, initial)
        self.deliver("sensor.distance_alpha", 7, 15)
        self.deliver("sensor.distance_beta", .9, 15.1)
        self.assertEqual(self.owner().location.observed_at, initial)
        self.assertEqual(next(iter(self.runtime._associations.anchors.values())).observed_at, at(3))
        self.second = 93
        self.runtime.refresh()
        self.assertNotEqual(self.owner().location.method, "anchored_device_handoff")
        self.assertIsNone(self.owner().location.area)
        self.assertFalse(self.runtime._associations.anchors)

    def test_restart_does_not_rebuild_anchor_from_saved_face_and_radio(self):
        self.seed(end=False)
        saved = self.runtime.export_state()
        self.runtime = PresenceRuntime(configuration(), now=lambda: at(self.second))
        self.runtime.restore_state(saved)
        self.assertFalse(self.runtime._associations.anchors)
        self.move()
        self.assertFalse(self.runtime._associations.handoffs)

    def test_owner_binding_and_receiver_identity_are_required(self):
        for key, value in (("device_id", "other_phone"), ("receiver_id", "alpha")):
            self.setUp()
            definitions = self.runtime._associations.definitions
            definition = definitions["distance_beta"]
            self.runtime._associations.definitions = {**definitions,
                "distance_beta": replace(definition, options={**definition.options, key: value})}
            self.seed(); self.move()
            self.assertNotEqual(self.owner().location.area, "beta")

    def test_channel_loss_retires_association_and_notifies_without_degrading_home(self):
        self.seed(); self.move()
        self.second = 14
        update = self.runtime.mark_channel_unavailable(("distance_beta",))
        self.assertTrue(update.changed)
        self.assertIsNone(self.owner().location.area)
        self.assertFalse(update.snapshot.coverage_degraded)
        self.assertEqual(update.detections, ())

    def test_missing_destination_baseline_needs_arrival_and_physical_destination(self):
        self.seed()
        anchor = next(iter(self.runtime._associations.anchors.values()))
        self.runtime._associations.anchors[("person_a", "phone_a")] = replace(anchor,
            ranges={"distance_alpha": anchor.ranges["distance_alpha"]})
        self.deliver("binary_sensor.alpha", "off", 8)
        self.move(physical=False)
        self.assertIsNone(self.owner().location.area)
        self.deliver("binary_sensor.beta", "on", 13)
        self.assertEqual(self.owner().location_status, "device_carried_probable")
        self.assertTrue(self.runtime.device_association_payload()[0]["requires_destination_body"])

    def test_measurement_expiry_is_scheduled_before_anchor_deadline(self):
        self.seed(); self.move()
        self.assertEqual(self.runtime.next_expiration(), at(31))
        self.second = 31
        self.assertTrue(self.runtime.refresh().changed)
        self.assertIsNone(self.owner().location.area)
        self.deliver("sensor.phone", "Beta", 33)
        self.assertIsNone(self.owner().location.area)

    def test_distinct_visual_visitors_are_not_consumed_by_radio_identity(self):
        self.seed(); self.move()
        for index in (1, 2):
            item = observation(f"visitor_{index}", family="visual_event", location=area("beta", 14),
                target_id=f"target_{index}", received=14, detected=14)
            item = replace(item, source=replace(item.source, native_id="camera_beta"))
            self.runtime._store.upsert(item)
        self.second = 14
        self.runtime._snapshot = self.runtime._resolve_snapshot()
        self.assertEqual(self.owner().location_status, "device_carried_probable")
        self.assertGreaterEqual(self.runtime.snapshot.count_minimum, 2)
        self.assertGreaterEqual(self.runtime.snapshot.count_maximum, 3)

    def test_other_owner_receiver_binding_cannot_carry_this_owner(self):
        definitions = self.runtime._associations.definitions
        self.runtime._associations.definitions = {sid: replace(d, identity="person_b") for sid, d in definitions.items()}
        self.seed(); self.move()
        self.assertFalse(self.runtime._associations.anchors)
        self.assertNotEqual(self.owner().location.area, "beta")

    def test_new_body_device_separation_invalidates_anchor_after_face_ends(self):
        self.seed(); self.move()
        self.body("alpha", 14)
        self.assertFalse(self.runtime._associations.anchors)
        self.assertEqual(self.owner().location.area, "alpha")
        self.body("alpha", 15, False)
        self.deliver("sensor.distance_beta", .9, 16)
        self.assertFalse(self.runtime._associations.handoffs)
        self.assertNotEqual(self.owner().location_status, "device_carried_probable")


if __name__ == "__main__":
    unittest.main()
