"""Endpoint attachments are device facts, not independent human bodies."""

from copy import deepcopy
import unittest

from presence_engine.adapters import AdapterEnvelope
from presence_engine.codec import decode_observation, encode_observation
from presence_engine.configuration import ConfigurationError, parse_configuration
from presence_engine.engine import ObservationStatus
from presence_engine.projection import snapshot_payload
from presence_engine.runtime import PresenceRuntime
from helpers import at, area, identity, observation


def configuration():
    return {"schema_version": 1, "areas": {"alpha": "ground", "beta": "ground"},
        "cameras": {}, "sources": [{"source_id": "wifi_a", "adapter": "wifi_tracker",
            "entity_ids": ["device_tracker.phone_a"], "identity": "person_a",
            "options": {"device_id": "phone_a", "ap_attribute": "connected_ap",
                        "ap_area_map": {"AP Alpha": "alpha", "AP Beta": "beta"}}}]}


class WifiTrackerTests(unittest.TestCase):
    def setUp(self):
        self.second = 0
        self.raw = configuration()
        self.runtime = PresenceRuntime(parse_configuration(self.raw), now=lambda: at(self.second))

    def deliver(self, state, second, ap="AP Alpha", *, observed=None, changed=0, extra=None):
        self.second = second
        return self.runtime.process(AdapterEnvelope("state", "device_tracker.phone_a", {
            "state": state, "attributes": {"source_type": "router", "connected_ap": ap, **(extra or {})},
            "last_changed": at(changed).isoformat(),
            "last_updated": at(second if observed is None else observed).isoformat()}, at(changed), at(second)))

    def test_owned_attachment_creates_only_low_proximity_not_confirmed_body(self):
        first = self.deliver("home", 1)
        second = self.deliver("home", 2, "AP Beta")
        self.assertTrue(first.changed and second.changed)
        device = second.snapshot.devices[0]
        self.assertEqual(device.network_attachment_area, "beta")
        self.assertEqual(device.network_attachment_observed_at, at(2))
        self.assertEqual(device.location.area, "beta")
        self.assertEqual(device.location.method, "wifi_ap_proximity")
        person = second.snapshot.presences[0]
        self.assertEqual(person.identity, "person_a")
        self.assertEqual(person.location.area, "beta")
        self.assertEqual(person.location.quality.value, "low")
        self.assertEqual(person.location_status, "possible")
        self.assertEqual(person.location.observed_at, at(2))
        self.assertEqual((second.snapshot.count_minimum, second.snapshot.count_maximum), (0, 1))
        self.assertEqual(second.snapshot.area_occupancies, ())
        saved = decode_observation(self.runtime.export_state()["observations"][0])
        self.assertIsNone(saved.location.area)  # Raw attachment remains a device fact.
        self.assertEqual(second.detections, ())
        self.assertEqual(second.failures, ())
        self.assertEqual(snapshot_payload(second.snapshot)["devices"][0]["network_attachment"], "AP Beta")

    def test_missing_mapping_attribute_and_owner_remain_explicit(self):
        self.raw["sources"][0].pop("identity")
        self.runtime = PresenceRuntime(parse_configuration(self.raw), now=lambda: at(self.second))
        device = self.deliver("home", 1, "Unmapped AP").snapshot.devices[0]
        self.assertIsNone(device.linked_identity)
        self.assertEqual(device.network_attachment, "Unmapped AP")
        self.assertIsNone(device.network_attachment_area)
        self.assertIsNone(device.location.area)
        self.assertIsNone(self.deliver("home", 2, None).snapshot.devices[0].network_attachment)
        self.assertEqual(self.deliver("home", 3, 42).failures, ())

    def test_unmapped_owned_device_retains_weak_home_estimate_and_no_body(self):
        update = self.deliver("home", 1, "Unmapped AP")
        person = update.snapshot.presences[0]
        self.assertIsNone(person.location.area)
        self.assertEqual(person.location.level.value, "home")
        self.assertEqual(person.location_status, "possible")
        self.assertEqual((update.snapshot.count_minimum, update.snapshot.count_maximum), (0, 1))

    def test_anonymous_radar_does_not_identify_ap_owner_or_create_ptz_vote(self):
        self.raw["sources"].append({"source_id": "radar", "adapter": "binary_presence",
            "entity_ids": ["binary_sensor.radar"], "area": "alpha", "spatial_quality": "high"})
        self.runtime = PresenceRuntime(parse_configuration(self.raw), now=lambda: at(self.second))
        self.deliver("home", 1)
        self.second = 2
        update = self.runtime.process(AdapterEnvelope("state", "binary_sensor.radar",
            {"state": "on"}, at(2), at(2)))
        owner = next(p for p in update.snapshot.presences if p.identity)
        self.assertEqual(owner.location.method, "wifi_ap_proximity")
        self.assertEqual(owner.location_status, "possible")
        self.assertEqual((update.snapshot.count_minimum, update.snapshot.count_maximum), (1, 2))
        self.assertNotIn("wifi_tracker", update.snapshot.area_occupancies[0].support_families)

    def test_absence_and_unknown_clear_attachment_without_degrading_coverage(self):
        for state, status in (("not_home", ObservationStatus.ENDED), ("unknown", ObservationStatus.UNKNOWN),
                              ("unavailable", ObservationStatus.UNKNOWN), ("Other Zone", ObservationStatus.UNKNOWN)):
            self.deliver("home", self.second + 1)
            update = self.deliver(state, self.second + 1, changed=self.second + 1)
            self.assertEqual(update.snapshot.devices, ())
            self.assertFalse(update.snapshot.coverage_degraded)
            saved = decode_observation(self.runtime.export_state()["observations"][0])
            self.assertEqual(saved.status, status)
            self.assertIsNone(saved.network_attachment)
            self.assertIsNone(saved.location)
            self.assertEqual(encode_observation(saved)["network_attachment"], None)

    def test_duplicate_noise_late_delivery_and_restart_do_not_renew_attachment(self):
        self.deliver("home", 1)
        self.deliver("home", 2, "AP Beta")
        for second, observed, ap in ((3, 1.5, "AP Alpha"), (4, 2, "AP Beta"), (5, 5, "AP Beta")):
            update = self.deliver("home", second, ap, observed=observed, extra={"friendly_name": "Renamed", "battery": 75})
            self.assertFalse(update.changed)
        saved = self.runtime.export_state()
        self.runtime = PresenceRuntime(parse_configuration(self.raw), now=lambda: at(self.second))
        self.runtime.restore_state(saved)
        self.assertFalse(self.deliver("home", 6, "AP Beta").changed)
        self.assertEqual(self.runtime.snapshot.devices[0].network_attachment_observed_at, at(2))
        self.deliver("not_home", 7, changed=7)
        self.assertFalse(self.deliver("home", 8, observed=6, changed=0).changed)
        self.assertEqual(self.runtime.snapshot.devices, ())
        self.assertEqual(self.deliver("home", 9, changed=9).snapshot.devices[0].network_attachment_observed_at, at(9))

    def test_camera_radar_and_phone_in_another_area_do_not_move_owner(self):
        self.raw["cameras"] = {"cam": {"floor": "ground", "fixed_area": "beta"}}
        self.raw["sources"] += [
            {"source_id": "events", "adapter": "frigate_events", "topics": ["vision/events"]},
            {"source_id": "faces", "adapter": "frigate_face", "topics": ["vision/faces"],
             "options": {"recognition_threshold": 0.8, "identity_map": {"Face A": "person_a"}}},
            {"source_id": "radar", "adapter": "binary_presence", "entity_ids": ["binary_sensor.radar"],
             "area": "beta", "spatial_quality": "high"}]
        self.runtime = PresenceRuntime(parse_configuration(self.raw), now=lambda: at(self.second))
        self.deliver("home", 1)
        self.second = 2
        def emit(kind, channel, payload):
            return self.runtime.process(AdapterEnvelope(kind, channel, payload, at(2), at(2)))
        emit("state", "binary_sensor.radar", {"state": "on"})
        emit("mqtt", "vision/events", {"type": "update", "after": {"id": "body_a", "camera": "cam",
            "label": "person", "start_time": at(2).timestamp(), "frame_time": at(2).timestamp(), "end_time": None}})
        update = emit("mqtt", "vision/faces", {"type": "face", "id": "body_a", "camera": "cam",
            "name": "Face A", "score": .95, "timestamp": at(2).timestamp()})
        self.assertEqual((update.snapshot.count_minimum, update.snapshot.count_maximum), (1, 1))
        self.assertEqual(update.snapshot.presences[0].location.area, "beta")
        self.assertEqual(update.snapshot.devices[0].network_attachment_area, "alpha")
        after = self.deliver("not_home", 3, changed=3).snapshot
        self.assertEqual(after.presences[0].identity, "person_a")
        self.assertEqual(after.presences[0].location.area, "beta")
        self.assertEqual((after.count_minimum, after.count_maximum), (1, 1))

    def test_ended_face_continues_at_original_clock_then_falls_back_to_ap(self):
        self.test_camera_radar_and_phone_in_another_area_do_not_move_owner()
        self.deliver("home", 4, changed=4)
        self.second = 5
        self.runtime.process(AdapterEnvelope("state", "binary_sensor.radar", {"state": "off"}, at(5), at(5)))
        update = self.runtime.process(AdapterEnvelope("mqtt", "vision/events", {"type": "end",
            "after": {"id": "body_a", "camera": "cam", "label": "person",
                "start_time": at(2).timestamp(), "frame_time": at(5).timestamp(),
                "end_time": at(5).timestamp()}}, at(5), at(5)))
        person = update.snapshot.presences[0]
        self.assertEqual(person.location.area, "beta")
        self.assertEqual(person.location_status, "continued")
        original = person.location.observed_at
        self.second = 100
        update = self.runtime.refresh()
        person = update.snapshot.presences[0]
        self.assertEqual(person.location.area, "alpha")
        self.assertEqual(person.location.method, "wifi_ap_proximity")
        self.assertEqual(person.location_status, "possible")
        self.assertEqual(person.location.observed_at, at(4))
        self.assertLess(original, at(100))
        self.assertEqual((update.snapshot.count_minimum, update.snapshot.count_maximum), (0, 1))
        self.assertEqual(update.detections, ())

    def test_conflicting_owned_aps_keep_home_and_alternatives_not_arbitrary_room(self):
        other = deepcopy(self.raw["sources"][0])
        other.update(source_id="wifi_b", entity_ids=["device_tracker.phone_b"])
        other["options"]["device_id"] = "phone_b"
        self.raw["sources"].append(other)
        self.runtime = PresenceRuntime(parse_configuration(self.raw), now=lambda: at(self.second))
        self.deliver("home", 1)
        self.second = 2
        update = self.runtime.process(AdapterEnvelope("state", "device_tracker.phone_b", {
            "state": "home", "attributes": {"source_type": "router", "connected_ap": "AP Beta"},
            "last_changed": at(2).isoformat(), "last_updated": at(2).isoformat()}, at(2), at(2)))
        self.assertEqual(len(update.snapshot.presences), 1)
        person = update.snapshot.presences[0]
        self.assertIsNone(person.location.area)
        self.assertEqual(set(person.candidate_areas), {"alpha", "beta"})
        self.assertEqual((update.snapshot.count_minimum, update.snapshot.count_maximum), (0, 1))

    def test_recent_personal_path_with_matching_ap_and_radar_is_medium_not_body_identity(self):
        self.test_camera_radar_and_phone_in_another_area_do_not_move_owner()
        self.deliver("home",4,"AP Beta",changed=4)
        self.second=5
        update=self.runtime.process(AdapterEnvelope("mqtt","vision/events",{"type":"end",
            "after":{"id":"body_a","camera":"cam","label":"person",
                "start_time":at(2).timestamp(),"frame_time":at(2).timestamp(),"end_time":at(5).timestamp()}},at(5),at(5)))
        person=next(p for p in update.snapshot.presences if p.identity)
        self.assertEqual(person.location.area,"beta")
        self.assertEqual(person.location_status,"continued")
        self.assertEqual(person.location.quality.value,"medium")
        self.assertEqual(person.location.observed_at,at(2))
        self.assertEqual(person.location_source_ids[0],"resolved-event:body_a")
        self.assertEqual(set(person.location_source_ids),{"resolved-event:body_a","wifi_a","radar"})
        self.assertEqual(person.identity_method,"registered_device_presence")
        self.assertEqual(person.identity_source_ids,("wifi_a",))
        self.assertEqual((update.snapshot.count_minimum,update.snapshot.count_maximum),(1,2))
        self.assertTrue(any(p.identity is None for p in update.snapshot.presences))
        self.assertEqual(update.snapshot.area_occupancies[0].support_families,("physical_presence",))
        self.assertIn("recent_personal_path_with_ap_and_body_support",update.snapshot.reasons)
        self.assertTrue(all(d.detection_id == "body_a" and d.detected_at == at(2) for d in update.detections))
        repeated=self.deliver("home",7,"AP Beta",changed=4)
        self.assertFalse(repeated.detections)
        self.assertEqual(next(p for p in self.runtime.snapshot.presences if p.identity).location.observed_at,at(2))
        self.second=92
        expired=self.runtime.refresh().snapshot
        person=next(p for p in expired.presences if p.identity)
        self.assertEqual(person.location.method,"wifi_ap_proximity")
        self.assertEqual(person.location.quality.value,"low")
        self.assertNotIn("radar",person.location_source_ids)
        self.assertNotIn("recent_personal_path_with_ap_and_body_support",expired.reasons)

    def test_ap_radar_corroboration_rejects_conflict_old_path_and_lost_support(self):
        for case in ("ap_conflict","old_path","radar_loss","ap_loss","multiple_people"):
            with self.subTest(case=case):
                self.setUp()
                self.test_camera_radar_and_phone_in_another_area_do_not_move_owner()
                self.deliver("home",4,"AP Alpha" if case=="ap_conflict" else "AP Beta",changed=4)
                self.second=25 if case=="old_path" else 5
                if case=="multiple_people":
                    self.runtime._store.upsert(observation("other-face",family="resolved_event",
                        target_id="other-body",location=area("beta",5),identity_claim=identity("person_b",5),received=5))
                self.runtime.process(AdapterEnvelope("mqtt","vision/events",{"type":"end",
                    "after":{"id":"body_a","camera":"cam","label":"person",
                        "start_time":at(2).timestamp(),"frame_time":at(2).timestamp(),"end_time":at(self.second).timestamp()}},at(self.second),at(self.second)))
                if case=="radar_loss":
                    self.runtime.mark_channel_unavailable(("radar",))
                elif case=="ap_loss":
                    self.deliver("not_home",6,changed=6)
                self.assertNotIn("recent_personal_path_with_ap_and_body_support",self.runtime.snapshot.reasons)

    def test_ap_body_support_rejects_recent_outside_gps_for_the_same_device(self):
        from dataclasses import replace
        from presence_engine.engine import GeographicPosition, TargetKind
        self.test_camera_radar_and_phone_in_another_area_do_not_move_owner()
        self.deliver("home",4,"AP Beta",changed=4)
        self.second=5
        gps=observation("gps",family="gps_tracker",kind=TargetKind.DEVICE,target_id="phone_a",
            identity_claim=identity("person_a",5,method="registered_owner"),received=5)
        self.runtime._store.upsert(replace(gps,geographic_position=GeographicPosition(
            1,1,5,at(5),"not_home","provider_timestamp")))
        update=self.runtime.process(AdapterEnvelope("mqtt","vision/events",{"type":"end",
            "after":{"id":"body_a","camera":"cam","label":"person",
                "start_time":at(2).timestamp(),"frame_time":at(2).timestamp(),"end_time":at(5).timestamp()}},at(5),at(5)))
        self.assertNotIn("recent_personal_path_with_ap_and_body_support",update.snapshot.reasons)
        owner=next(p for p in update.snapshot.presences if p.identity)
        self.assertEqual(owner.location.observed_at,at(2))
        self.assertEqual(owner.location_source_ids[0],"resolved-event:body_a")
        self.assertNotIn("wifi_a",owner.location_source_ids)

    def test_metadata_does_not_accept_gps_as_wifi_or_copy_private_attributes(self):
        update = self.deliver("home", 1, extra={"source_type": "gps", "tracking_type": "position"})
        self.assertEqual(update.snapshot.devices, ())
        self.assertFalse(update.snapshot.coverage_degraded)
        self.deliver("home", 2, extra={"token": "fixture-secret", "latitude": 1, "ip_address": "192.0.2.1"})
        self.assertNotIn("fixture-secret", str(self.runtime.export_state()))
        self.assertNotIn("192.0.2.1", str(self.runtime.export_state()))
        self.assertEqual(self.deliver("home", 3, observed=4).failures[0].error_type, "ValueError")
        self.assertEqual(self.runtime.snapshot.devices, ())
        self.assertEqual(len(self.deliver("home", 5).snapshot.devices), 1)
        self.runtime.mark_channel_unavailable(("wifi_a",))
        self.assertEqual(len(self.deliver("home", 6).snapshot.devices), 1)

    def test_configuration_change_does_not_restore_old_attachment_mapping(self):
        self.deliver("home", 1)
        saved = self.runtime.export_state()
        self.raw["sources"][0]["options"]["ap_area_map"]["AP Alpha"] = "beta"
        self.runtime = PresenceRuntime(parse_configuration(self.raw), now=lambda: at(self.second))
        self.runtime.restore_state(saved)
        self.assertEqual(self.runtime.snapshot.devices, ())
        self.assertEqual(self.deliver("home", 2).snapshot.devices[0].network_attachment_area, "beta")
        self.raw["sources"][0]["options"]["ap_attribute"] = "other_ap"
        self.runtime = PresenceRuntime(parse_configuration(self.raw), now=lambda: at(self.second))
        self.runtime.restore_state(saved)
        self.assertEqual(self.runtime.snapshot.devices, ())
        self.assertIsNone(self.deliver("home", 3).snapshot.devices[0].network_attachment)
        corrupt = deepcopy(saved)
        corrupt["observations"][0]["target_kind"] = "person"
        self.runtime = PresenceRuntime(parse_configuration(configuration()), now=lambda: at(self.second))
        self.runtime.restore_state(corrupt)
        self.assertEqual(self.runtime.snapshot.presences, ())
        self.assertEqual(self.runtime.snapshot.devices, ())

    def test_invalid_configuration_is_rejected(self):
        for key, value in (("device_id", ""), ("ap_attribute", ""), ("ap_attribute", "access_token"), ("ap_area_map", []),
                           ("ap_area_map", {"AP": "missing"})):
            raw = configuration(); raw["sources"][0]["options"][key] = value
            with self.assertRaises(ConfigurationError):
                parse_configuration(raw)
        for key, value in (("availability_role", "coverage"), ("area", "alpha"),
                           ("entity_ids", ["sensor.phone"]), ("entity_ids", ["device_tracker.a", "device_tracker.b"])):
            raw = configuration(); raw["sources"][0][key] = value
            with self.assertRaises(ConfigurationError):
                parse_configuration(raw)
        raw = deepcopy(configuration()); raw["sources"][0]["options"].pop("ap_attribute")
        with self.assertRaises(ConfigurationError):
            parse_configuration(raw)


if __name__ == "__main__":
    unittest.main()
