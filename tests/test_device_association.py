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
        self.setUp(); self.late_arrival()
        saved = self.runtime.export_state()
        self.runtime = PresenceRuntime(configuration(), now=lambda: at(93.1))
        self.runtime.restore_state(saved)
        self.assertFalse(self.runtime._associations.handoffs)
        self.assertNotEqual(self.owner().location_status, "device_carried_probable")

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
        self.assertFalse(self.runtime.refresh().changed, "old origin range no longer cancels a completed arrival")
        self.assertEqual(self.runtime.next_expiration(), at(31.1))
        self.second = 31.1
        self.assertTrue(self.runtime.refresh().changed)
        self.assertIsNone(self.owner().location.area)
        self.deliver("sensor.phone", "Beta", 33)
        self.assertIsNone(self.owner().location.area)

    def late_arrival(self):
        self.seed()
        self.deliver("sensor.phone", "Beta", 90)
        self.deliver("sensor.distance_alpha", 5, 90.1)
        self.deliver("sensor.distance_beta", 1.2, 90.2)
        self.deliver("sensor.distance_alpha", 6, 91)
        self.deliver("sensor.distance_beta", 1, 91.1)
        self.deliver("binary_sensor.beta", "on", 92.9)
        self.assertEqual(self.owner().location_status, "device_carried_probable")

    def test_completed_arrival_survives_origin_anchor_expiry_without_renewing_clocks(self):
        self.late_arrival()
        spatial = self.owner().location.observed_at
        self.second = 93.1
        self.assertFalse(self.runtime.refresh().changed)
        self.assertFalse(self.runtime._associations.anchors)
        self.assertEqual(self.owner().location.area, "beta")
        for second in range(100, 181, 10):
            self.deliver("sensor.distance_beta", 1 + second / 1000, second)
            self.assertEqual(self.owner().location.area, "beta")
            self.assertEqual(self.owner().location.observed_at, spatial)
            self.assertEqual(self.owner().identity_observed_at, at(2))
        detail = self.runtime.device_association_payload()[0]
        self.assertEqual(detail["anchored_at"], at(3).isoformat())
        self.assertEqual(detail["arrival_accepted_at"], at(92.9).isoformat())
        self.assertEqual(detail["arrival_expires_at"], at(182.9).isoformat())
        self.assertEqual(self.runtime.next_expiration(), at(182.9))
        self.second = 182.9
        self.assertTrue(self.runtime.refresh().changed)
        self.assertIsNone(self.owner().location.area, "positive radio cannot renew the arrival indefinitely")

    def test_completed_arrival_cancels_on_clear_device_departure_invalid_radio_or_new_body(self):
        for cause in ("clear", "departure", "invalid", "body"):
            with self.subTest(cause=cause):
                self.setUp(); self.late_arrival()
                self.second = 93.1
                self.runtime.refresh()
                if cause == "body":
                    self.body("alpha", 93.2)
                    self.assertEqual(self.owner().location.area, "alpha")
                else:
                    channel, value = {"clear": ("binary_sensor.beta", "off"),
                        "departure": ("sensor.phone", "Alpha"),
                        "invalid": ("sensor.distance_beta", "unavailable")}[cause]
                    self.deliver(channel, value, 93.2)
                    self.assertIsNone(self.owner().location.area)
                self.assertFalse(self.runtime._associations.handoffs)

    def test_uncompleted_transfer_does_not_extend_origin_deadline(self):
        self.seed()
        self.deliver("sensor.phone", "Beta", 90)
        for name, value, second in (("alpha", 5, 90.1), ("beta", 1.2, 90.2),
                                   ("alpha", 6, 91), ("beta", 1, 91.1)):
            self.deliver(f"sensor.distance_{name}", value, second)
        self.second = 93.1
        self.runtime.refresh()
        self.deliver("binary_sensor.beta", "on", 93.2)
        self.assertNotEqual(self.owner().location.area, "beta")
        self.assertFalse(self.runtime._associations.handoffs)

    def correlated_seed(self):
        definition = configuration()
        sources = tuple(replace(s, entity_ids=(*s.entity_ids, "sensor.position_alpha"),
            options={**s.options, "radar_channels": {"sensor.position_alpha":
                {"metric": "distance", "target_slot": "aggregate"}}}) if s.source_id == "radar_alpha" else s
            for s in definition.sources)
        self.runtime = PresenceRuntime(replace(definition, sources=sources), now=lambda: at(self.second))
        for entity, value, second in (("sensor.distance_alpha", 1, 0), ("sensor.distance_beta", 5, .1),
                                      ("sensor.distance_alpha", 1.2, 1), ("sensor.distance_beta", 5.2, 1.1),
                                      ("person.owner", "home", 2), ("sensor.phone", "Alpha", 2.1),
                                      ("binary_sensor.alpha", "on", 3), ("sensor.position_alpha", .8, 4),
                                      ("sensor.position_alpha", .9, 5), ("sensor.distance_alpha", 1.1, 5.1)):
            self.deliver(entity, value, second)

    def correlated_move(self, clear=True, physical=True):
        if clear:
            self.deliver("binary_sensor.alpha", "off", 8)
        for entity, value, second in (("sensor.distance_alpha", 5, 11), ("sensor.distance_beta", 1.2, 11.1),
                                      ("sensor.distance_alpha", 6, 12), ("sensor.distance_beta", 1, 12.1)):
            self.deliver(entity, value, second)
        if physical:
            return self.deliver("binary_sensor.beta", "on", 13)
        return self.runtime.snapshot

    def test_correlated_body_measurements_and_clear_can_follow_radio_before_area_label(self):
        self.correlated_seed()
        old_counter = self.runtime._store.get("radar_alpha", "radar_alpha").observation
        update = self.correlated_move()
        self.assertEqual(self.owner().location.area, "beta")
        self.assertEqual(self.owner().location_status, "device_carried_probable")
        self.assertEqual(self.owner().location.quality, Quality.MEDIUM)
        self.assertEqual(self.owner().identity_observed_at, at(2))
        self.assertEqual(old_counter.location.observed_at, at(3))
        self.assertEqual(self.runtime.snapshot.devices[0].location.area, "alpha")
        self.assertEqual(update.detections, ())
        detail = self.runtime.device_association_payload()[0]
        self.assertEqual(detail["anchored_at"], at(5).isoformat())
        self.assertTrue(detail["requires_origin_clear"])
        self.assertEqual(detail["origin_measurement_channels"], ["sensor.position_alpha"])

    def test_correlated_radio_requires_origin_clear_and_destination_body(self):
        for clear, physical in ((False, True), (True, False)):
            self.setUp(); self.correlated_seed(); self.correlated_move(clear, physical)
            self.assertNotEqual(self.owner().location.area, "beta")

    def test_correlated_phone_left_or_area_jump_does_not_identify_destination(self):
        for area_jump in (False, True):
            with self.subTest(area_jump=area_jump):
                self.setUp(); self.correlated_seed()
                self.deliver("binary_sensor.alpha", "off", 8)
                if area_jump:
                    self.deliver("sensor.phone", "Beta", 10)
                for entity, value, second in (("sensor.distance_alpha", 1.1, 11), ("sensor.distance_beta", 5, 11.1),
                                              ("sensor.distance_alpha", 1.2, 12), ("sensor.distance_beta", 5.1, 12.1)):
                    self.deliver(entity, value, second)
                self.deliver("binary_sensor.beta", "on", 13)
                self.assertFalse(self.runtime._associations.handoffs)
                self.assertNotEqual(self.owner().location_status, "device_carried_probable")
                if not area_jump:
                    self.assertNotEqual(self.owner().location.area, "beta")
                # Area label + body uses the existing ordinary association,
                # not a trajectory: this check makes no claim to fix that path.

    def test_correlated_anchor_uses_new_body_clocks_not_aliases_or_restart(self):
        self.correlated_seed()
        anchored = next(iter(self.runtime._associations.anchors.values())).observed_at
        self.deliver("sensor.distance_alpha", 1.15, 6)
        self.assertEqual(next(iter(self.runtime._associations.anchors.values())).observed_at, anchored)
        self.deliver("sensor.position_alpha", 90, 6.1, "cm")
        self.deliver("sensor.distance_alpha", 1.16, 6.2)
        self.assertEqual(next(iter(self.runtime._associations.anchors.values())).observed_at, anchored)
        saved = self.runtime.export_state()
        self.runtime = PresenceRuntime(self.runtime.configuration, now=lambda: at(self.second))
        self.runtime.restore_state(saved)
        self.assertFalse(self.runtime._associations.anchors)
        self.correlated_move()
        self.assertNotEqual(self.owner().location.area, "beta")

    def test_correlated_acceptance_keeps_deadline_and_current_identified_body_wins(self):
        self.correlated_seed(); self.correlated_move()
        accepted = next(iter(self.runtime._associations.handoffs.values())).accepted_at
        self.deliver("sensor.distance_alpha", 7, 14)
        self.deliver("sensor.distance_beta", .9, 14.1)
        self.assertEqual(next(iter(self.runtime._associations.handoffs.values())).accepted_at, accepted)
        self.body("alpha", 15)
        self.assertEqual(self.owner().location.area, "alpha")
        self.assertEqual(self.owner().identity_observed_at, at(15))
        self.assertFalse(self.runtime._associations.handoffs)

    def test_correlated_arrival_rejects_other_identity_and_expires_without_new_body(self):
        self.correlated_seed()
        self.body("beta", 7, owner="person_b")
        self.correlated_move()
        self.assertFalse(self.runtime._associations.handoffs)
        self.assertNotEqual(self.owner().location_status, "device_carried_probable")
        self.setUp(); self.correlated_seed(); self.correlated_move()
        for second in range(20, 104, 10):
            self.deliver("sensor.distance_alpha", 7 + second / 1000, second)
            self.deliver("sensor.distance_beta", .9 + second / 1000, second + .1)
        self.second = 104
        self.runtime.refresh()
        self.assertFalse(self.runtime._associations.handoffs)
        self.assertIsNone(self.owner().location.area)

    def test_current_face_cannot_be_moved_by_adjacent_anonymous_body(self):
        cfg = configuration()
        self.runtime = PresenceRuntime(replace(cfg, adjacency={"alpha": ("beta",)}), now=lambda: at(self.second))
        self.body("alpha", 1)
        self.deliver("binary_sensor.beta", "on", 2)
        self.assertEqual(self.owner().location.area, "alpha")
        self.assertEqual(self.owner().location.observed_at, at(1))
        self.assertGreaterEqual(self.runtime.snapshot.count_maximum, 2)

    def test_correlated_arrival_expires_without_callbacks(self):
        self.correlated_seed(); self.correlated_move()
        self.second = 94
        self.runtime.refresh()
        self.assertEqual(self.owner().location_status, "continued")
        self.assertEqual(self.runtime.next_expiration(), at(95))
        self.second = 104
        self.assertTrue(self.runtime.refresh().changed)
        self.assertIsNone(self.owner().location.area)

    def test_new_destination_needs_new_body_not_the_previous_arrival_clock(self):
        cfg = configuration()
        beta = next(s for s in cfg.sources if s.source_id == "radar_beta")
        signal = next(s for s in cfg.sources if s.source_id == "distance_beta")
        sources = tuple(replace(s, options={**s.options, "area_map": {"Alpha": "alpha", "Beta": "beta", "Gamma": "gamma"}})
            if s.source_id == "phone" else s for s in cfg.sources)
        sources += (replace(beta, source_id="radar_gamma", area="gamma", entity_ids=("binary_sensor.gamma",)),
                    replace(signal, source_id="distance_gamma", area="gamma", entity_ids=("sensor.distance_gamma",),
                        options={**signal.options, "receiver_id": "gamma"}))
        self.runtime = PresenceRuntime(replace(cfg, areas={**cfg.areas, "gamma": "upper"}, sources=sources),
                                       now=lambda: at(self.second))
        for entity, value, second in (("sensor.distance_alpha", 1, 0), ("sensor.distance_beta", 5, .1),
                                      ("sensor.distance_gamma", 5, .2), ("sensor.distance_alpha", 1.2, 1),
                                      ("sensor.distance_beta", 5.2, 1.1), ("sensor.distance_gamma", 5.2, 1.2),
                                      ("person.owner", "home", 2), ("sensor.phone", "Alpha", 2.1)):
            self.deliver(entity, value, second)
        self.body("alpha", 3); self.deliver("binary_sensor.alpha", "on", 4); self.body("alpha", 5, False)
        self.move()
        self.assertEqual(self.owner().location.area, "beta")
        self.deliver("binary_sensor.gamma", "on", 14)
        self.deliver("sensor.phone", "Gamma", 20)
        for entity, value, second in (("sensor.distance_alpha", 7, 20.1), ("sensor.distance_gamma", 1.2, 20.2),
                                      ("sensor.distance_alpha", 8, 21), ("sensor.distance_gamma", 1, 21.1)):
            self.deliver(entity, value, second)
        self.assertEqual(self.owner().location.area, "gamma")
        detail = self.runtime.device_association_payload()[0]
        self.assertEqual(detail["arrival_accepted_at"], at(21.1).isoformat())
        self.assertEqual(detail["arrival_expires_at"], at(111.1).isoformat())
        self.deliver("sensor.distance_gamma", .9, 23)
        self.assertEqual(self.runtime.device_association_payload()[0]["arrival_accepted_at"], at(21.1).isoformat())
        self.deliver("sensor.phone", "Beta", 24)
        for entity, value, second in (("sensor.distance_alpha", 9, 24.1), ("sensor.distance_beta", .8, 24.2),
                                      ("sensor.distance_alpha", 10, 25), ("sensor.distance_beta", .7, 25.1)):
            self.deliver(entity, value, second)
        self.assertNotEqual(self.owner().location.area, "beta", "the held body predates the last accepted arrival")
        self.assertEqual(next(iter(self.runtime._associations.anchors.values())).accepted_at, at(21.1))

    def test_origin_clear_cannot_restore_arrival_after_destination_clears(self):
        self.seed()
        self.deliver("binary_sensor.alpha", "off", 8)
        self.move()
        self.deliver("binary_sensor.beta", "off", 14)
        self.assertIsNone(self.owner().location.area)
        self.deliver("sensor.distance_beta", .9, 15)
        self.assertIsNone(self.owner().location.area)

    def test_area_oscillation_cannot_roll_accepted_arrival_deadline(self):
        self.seed(); self.move()
        accepted = next(iter(self.runtime._associations.handoffs.values())).accepted_at
        self.deliver("sensor.phone", "Alpha", 14)
        self.deliver("sensor.phone", "Beta", 15)
        self.assertFalse(self.runtime._associations.handoffs, "an area flip is not a new corroborated arrival")
        self.assertEqual(next(iter(self.runtime._associations.anchors.values())).accepted_at, accepted)

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

    def enable_beta_telemetry(self):
        config = configuration()
        source = next(s for s in config.sources if s.source_id == "radar_beta")
        channels = {"sensor.beta_x": {"target_slot": "slot_1", "metric": "x"},
                    "sensor.beta_speed": {"target_slot": "slot_1", "metric": "speed"}}
        source = replace(source, entity_ids=(*source.entity_ids, *channels), options={"radar_channels": channels})
        self.runtime = PresenceRuntime(replace(config, sources=tuple(
            source if s.source_id == source.source_id else s for s in config.sources)), now=lambda: at(self.second))

    def pending_motion_arrival(self):
        self.enable_beta_telemetry()
        self.deliver("binary_sensor.beta", "on", 0)
        self.seed()
        self.deliver("sensor.phone", "Beta", 40)
        for name, value, second in (("alpha", 5, 41), ("beta", 1.2, 41.1),
                                    ("alpha", 6, 42), ("beta", 1, 42.1)):
            self.deliver(f"sensor.distance_{name}", value, second)
        self.assertNotEqual(self.owner().location.area, "beta")

    def radar_motion(self, speed=-80, final=150):
        self.deliver("sensor.beta_x", 100, 43, "mm")
        self.deliver("sensor.beta_x", 120, 44, "mm")
        self.deliver("sensor.beta_speed", speed, 44.1, "mm/s")
        return self.deliver("sensor.beta_x", final, 45, "mm")

    def test_recent_radar_motion_corroborates_radio_without_refreshing_held_count(self):
        self.pending_motion_arrival()
        original = next(o for o in self.runtime._store.values() if o.source.source_id == "radar_beta")
        update = self.radar_motion()
        self.assertTrue(update.changed)
        self.assertEqual(self.owner().location.area, "beta")
        self.assertEqual(self.owner().location_status, "device_carried_probable")
        self.assertEqual(self.owner().location.quality, Quality.MEDIUM)
        self.assertEqual(self.owner().location.observed_at, at(42.1))
        self.assertEqual(self.owner().identity_observed_at, at(2))
        self.assertEqual(next(o for o in self.runtime._store.values() if o.source.source_id == "radar_beta"), original)
        self.assertEqual((update.snapshot.count_minimum, update.snapshot.count_maximum), (1, 2))
        self.assertEqual(update.detections, ())
        self.assertIn("radar_motion_corroborated_device_handoff", update.snapshot.reasons)

    def test_radar_noise_stationary_missing_speed_and_sparse_spike_do_not_transfer(self):
        for speed, final in ((0, 150), ("unknown", 150), (-80, 110), (-80, 120)):
            with self.subTest(speed=speed, final=final):
                self.setUp(); self.pending_motion_arrival()
                update = self.radar_motion(speed, final)
                self.assertNotEqual(self.owner().location.area, "beta")
                self.assertFalse(update.changed)

    def test_motion_is_not_a_body_or_a_radio_trajectory(self):
        for cause in ("clear", "area_only", "face"):
            with self.subTest(cause=cause):
                self.setUp(); self.pending_motion_arrival()
                if cause == "clear":
                    self.deliver("binary_sensor.beta", "off", 42.2)
                elif cause == "area_only":
                    self.deliver("sensor.distance_beta", "unknown", 42.2)
                else:
                    self.body("alpha", 42.2)
                self.radar_motion()
                self.assertNotEqual(self.owner().location.area, "beta")

    def test_motion_arrival_clock_is_fixed_and_restart_does_not_restore_it(self):
        self.pending_motion_arrival(); self.radar_motion()
        initial = self.owner().location
        self.assertEqual(self.owner().location.area, "beta")
        for second in range(50, 131, 10):
            self.deliver("sensor.distance_beta", 1 + second / 1000, second)
            self.assertEqual(self.owner().location, initial)
        detail = self.runtime.device_association_payload()[0]
        self.assertEqual(detail["arrival_accepted_at"], at(45).isoformat())
        self.assertEqual(detail["arrival_expires_at"], at(135).isoformat())
        self.second = 135
        self.assertTrue(self.runtime.refresh().changed)
        self.assertIsNone(self.owner().location.area)
        self.setUp(); self.pending_motion_arrival(); self.radar_motion()
        saved = self.runtime.export_state()
        self.runtime = PresenceRuntime(self.runtime.configuration, now=lambda: at(45))
        self.runtime.restore_state(saved)
        self.assertFalse(self.runtime._associations.handoffs)
        self.assertNotEqual(self.owner().location_status, "device_carried_probable")

    def test_motion_arrival_keeps_visitors_and_retires_on_observer_loss_or_clear(self):
        for cause in ("clear", "unavailable", "geometry_only"):
            with self.subTest(cause=cause):
                self.setUp(); self.pending_motion_arrival(); self.radar_motion()
                self.assertTrue(any(p.identity is None and p.location.area == "alpha"
                                    for p in self.runtime.snapshot.presences))
                channel, value = {"clear": ("binary_sensor.beta", "off"),
                    "unavailable": ("binary_sensor.beta", "unavailable"),
                    "geometry_only": ("sensor.beta_x", "unknown")}[cause]
                update = self.deliver(channel, value, 46, "mm")
                if cause == "geometry_only":
                    self.assertEqual(self.owner().location.area, "beta")
                    self.assertFalse(update.changed, "optional geometry loss is not body absence")
                    self.assertEqual(self.runtime.device_association_payload()[0]["arrival_accepted_at"], at(45).isoformat())
                else:
                    self.assertIsNone(self.owner().location.area)
                    self.assertFalse(self.runtime._associations.handoffs)


if __name__ == "__main__":
    unittest.main()
