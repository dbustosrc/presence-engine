"""GPS is device evidence; light/media activity never creates a body."""

import unittest

from helpers import at, area, identity, observation
from presence_engine.adapters import AdapterEnvelope
from presence_engine.codec import decode_observation, encode_observation
from presence_engine.configuration import ConfigurationError, parse_configuration
from presence_engine.engine import Quality, SpatialLevel
from presence_engine.projection import snapshot_payload
from presence_engine.public_projection import public_presence_projection
from presence_engine.runtime import PresenceRuntime


def config():
    return {"schema_version":1,"areas":{"alpha":"ground","beta":"ground"},"sources":[
        {"source_id":"gps","adapter":"gps_tracker","entity_ids":["device_tracker.phone"],
         "identity":"owner","expires_after_seconds":30,"options":{"device_id":"phone"}},
        {"source_id":"lamp","adapter":"auxiliary_activity","area":"alpha","entity_ids":["light.lamp"],
         "dependency_group":"consumer","options":{"activity_origin":"presence_derived"}},
        {"source_id":"tv","adapter":"auxiliary_activity","area":"alpha","entity_ids":["media_player.tv"],
         "options":{"active_states":["playing"]}}]}


class GpsActivityTests(unittest.TestCase):
    def setUp(self):
        self.raw=config(); self.second=0
        self.runtime=PresenceRuntime(parse_configuration(self.raw),now=lambda:at(self.second))

    def deliver(self, entity, state, second, attributes=None, updated=None):
        self.second=second
        return self.runtime.process(AdapterEnvelope("state",entity,{"state":state,
            "attributes":attributes or {},"last_updated":at(second if updated is None else updated).isoformat(),
            "last_changed":at(second).isoformat()},at(second),at(second)))

    def gps(self, state="home", second=1, **attributes):
        return self.deliver("device_tracker.phone",state,second,{"source_type":"gps",
            "latitude":10.0,"longitude":20.0,"gps_accuracy":100,**attributes})

    def test_gps_home_is_only_weak_personal_scope_not_a_room_or_body(self):
        update=self.gps()
        p,=update.snapshot.presences
        self.assertEqual((p.location.level,p.location.area,p.location_status,p.location.quality),
                         (SpatialLevel.HOME,None,"possible",Quality.LOW))
        self.assertEqual((update.snapshot.count_minimum,update.snapshot.count_maximum),(0,1))
        self.assertFalse(update.snapshot.area_occupancies or update.detections)
        geo=snapshot_payload(update.snapshot)["devices"][0]["geographic_position"]
        self.assertEqual((geo["coordinate_unit"],geo["accuracy_unit"],geo["accuracy_m"]),("degrees","m",100))
        self.assertTrue(geo["device_only"])

    def test_gps_away_named_zone_and_unowned_endpoint_do_not_invent_home(self):
        for second,state in enumerate(("not_home","Work","Office"),1):
            update=self.gps(state, second)
            self.assertFalse(update.snapshot.presences)
            self.assertEqual(update.snapshot.devices[0].geographic_position.native_zone,state)
            self.assertIsNone(update.snapshot.devices[0].location.area)
        self.raw["sources"][0].pop("identity")
        self.runtime=PresenceRuntime(parse_configuration(self.raw),now=lambda:at(self.second))
        self.assertFalse(self.gps().snapshot.presences)

    def test_gps_outside_never_moves_recognized_person_or_creates_another(self):
        self.gps("not_home")
        self.runtime._store.upsert(observation("face",identity_claim=identity("owner",2),location=area("beta",2)))
        self.second=2; self.runtime._snapshot=self.runtime._resolve_snapshot()
        p,=self.runtime.snapshot.presences
        self.assertEqual(p.location.area,"beta")
        self.assertEqual((self.runtime.snapshot.count_minimum,self.runtime.snapshot.count_maximum),(1,1))

    def test_position_updates_not_metadata_are_clocked_and_restored_without_renewal(self):
        self.gps(second=1)
        self.assertFalse(self.gps(second=2,battery_level=20).changed)
        self.assertEqual(self.runtime.next_expiration(),at(31))
        self.gps(second=3,latitude=11)
        self.assertEqual(self.runtime.snapshot.devices[0].geographic_position.latitude,11)
        self.assertEqual(self.runtime.snapshot.devices[0].geographic_position.observed_at,at(3))
        saved=self.runtime.export_state()
        decoded=decode_observation(saved["observations"][0])
        self.assertEqual(encode_observation(decoded),saved["observations"][0])
        self.runtime=PresenceRuntime(parse_configuration(self.raw),now=lambda:at(self.second))
        self.runtime.restore_state(saved)
        self.assertFalse(self.gps(second=4,latitude=11).changed)
        self.second=33; self.assertTrue(self.runtime.refresh().changed)
        self.assertFalse(self.runtime.snapshot.devices or self.runtime.snapshot.presences)

    def test_provider_clock_late_delivery_expiry_future_and_binding_change(self):
        self.raw["sources"][0]["options"]["timestamp_attribute"]="last_seen"
        self.runtime=PresenceRuntime(parse_configuration(self.raw),now=lambda:at(self.second))
        self.gps(second=10,last_seen=at(2).isoformat())
        self.assertEqual(self.runtime.next_expiration(),at(32))
        self.assertFalse(self.gps(second=11,last_seen=at(1).isoformat()).changed)
        self.gps(second=12,last_seen=at(3).isoformat())
        self.assertEqual(self.runtime.snapshot.devices[0].geographic_position.observed_at,at(3))
        saved=self.runtime.export_state()
        self.raw["sources"][0]["options"]["timestamp_attribute"]="other_clock"
        self.runtime=PresenceRuntime(parse_configuration(self.raw),now=lambda:at(self.second))
        self.runtime.restore_state(saved)
        self.assertFalse(self.runtime.snapshot.devices)
        self.assertTrue(self.gps(second=13,other_clock=at(14).isoformat()).failures)
        self.assertFalse(self.runtime.snapshot.coverage_degraded)

    def test_delayed_fix_is_already_stale_and_unknown_withdraws_only_gps(self):
        self.gps(second=1)
        update=self.deliver("device_tracker.phone","home",100,{"source_type":"gps",
            "latitude":11,"longitude":20,"gps_accuracy":50},updated=2)
        self.assertFalse(update.snapshot.devices or update.snapshot.presences)
        self.assertIsNone(self.runtime.next_expiration())
        self.assertEqual(self.runtime.gps_status_payload()[0]["status"],"stale")
        self.gps(second=101,latitude=11)
        self.assertEqual(self.runtime.gps_status_payload()[0]["status"],"fresh")
        self.deliver("light.lamp","on",102)
        update=self.deliver("device_tracker.phone","unknown",103)
        self.assertFalse(update.snapshot.devices or update.snapshot.presences or update.snapshot.coverage_degraded)
        self.assertTrue(update.snapshot.area_activity)

    def test_bad_coordinates_precision_and_label_only_gps_remove_support_not_coverage(self):
        for attrs in ({"latitude":None},{"latitude":float("nan")},{"latitude":91},{"longitude":181},
                      {"gps_accuracy":-1},{"gps_accuracy":None},{"gps_accuracy":True},
                      {"source_type":"router"},{"tracking_type":"connection"}):
            self.setUp(); self.gps()
            update=self.gps(second=2,**attrs)
            self.assertTrue(update.failures)
            self.assertFalse(update.snapshot.devices or update.snapshot.coverage_degraded)
        self.setUp(); self.gps(second=1,gps_accuracy=0)
        self.assertEqual(self.runtime.snapshot.devices[0].geographic_position.accuracy_m,0)
        self.assertEqual(self.runtime.snapshot.presences[0].location.quality,Quality.LOW)

    def test_activity_has_sources_clocks_and_dependencies_but_zero_bodies(self):
        self.assertFalse(self.runtime.gps_status_payload()[0]["coordinates_available"])
        self.deliver("light.lamp","on",1)
        update=self.deliver("media_player.tv","playing",2)
        self.assertFalse(update.snapshot.presences or update.snapshot.devices or update.snapshot.area_occupancies or update.detections)
        self.assertEqual((update.snapshot.count_minimum,update.snapshot.count_maximum),(0,0))
        a,=public_presence_projection(update.snapshot)["area_activity"]
        self.assertEqual((a["area"],a["confidence"],a["identity"],a["body_count"]),("alpha","low",None,None))
        self.assertEqual(a["derived_sources"],["lamp"])
        self.assertEqual(a["unknown_origin_sources"],["tv"])
        self.assertEqual(a["dependency_groups"],["consumer"])
        self.assertFalse(public_presence_projection(update.snapshot)["active_areas"])
        self.deliver("media_player.tv","paused",3)
        self.assertEqual(self.runtime.snapshot.area_activity[0].source_ids,("lamp",))
        self.deliver("light.lamp","unavailable",4)
        self.assertFalse(self.runtime.snapshot.area_activity or self.runtime.snapshot.coverage_degraded)

    def test_activity_cannot_raise_facial_or_radar_confidence_or_count(self):
        self.runtime._store.upsert(observation("face",identity_claim=identity("owner",1),location=area("beta",1)))
        self.second=1; self.runtime._snapshot=self.runtime._resolve_snapshot()
        initial=self.runtime.snapshot.presences
        self.deliver("light.lamp","on",2)
        self.assertEqual(initial,self.runtime.snapshot.presences)
        self.assertEqual((self.runtime.snapshot.count_minimum,self.runtime.snapshot.count_maximum),(1,1))

    def test_reload_requalifies_activity_with_current_area_and_provenance(self):
        self.deliver("light.lamp","on",1)
        saved=self.runtime.export_state()
        self.raw["sources"][1]["area"]="beta"
        self.raw["sources"][1]["options"]["activity_origin"]="unknown"
        self.runtime=PresenceRuntime(parse_configuration(self.raw),now=lambda:at(self.second))
        self.runtime.restore_state(saved)
        self.assertFalse(self.runtime.snapshot.area_activity)
        self.deliver("light.lamp","on",2)
        self.assertEqual(self.runtime.snapshot.area_activity[0].area,"beta")
        self.assertEqual(self.runtime.snapshot.area_activity[0].unknown_origin_source_ids,("lamp",))

    def test_invalid_source_configuration_is_rejected(self):
        for adapter, changes in (("gps_tracker",{"area":"alpha"}),("gps_tracker",{"availability_role":"coverage"}),
            ("gps_tracker",{"entity_ids":["sensor.bad"]}),("auxiliary_activity",{"identity":"owner"}),
            ("auxiliary_activity",{"area":None}),("auxiliary_activity",{"entity_ids":["sensor.bad"]})):
            raw=config(); raw["sources"]=[next(s for s in raw["sources"] if s["adapter"]==adapter)]
            raw["sources"][0].update(changes)
            with self.assertRaises(ConfigurationError):parse_configuration(raw)

    def test_geographic_confidence_is_for_device_fix_not_person_or_room(self):
        self.raw["sources"][0]["options"]["timestamp_attribute"]="last_seen"
        self.runtime=PresenceRuntime(parse_configuration(self.raw),now=lambda:at(self.second))
        for second,state,accuracy,expected in ((1,"not_home",23,"high"),(2,"Work",100,"medium"),
                (3,"not_home",300,"low"),(4,"home",5,"low"),(5,"not_home",0,"unknown")):
            update=self.gps(state,second,gps_accuracy=accuracy,last_seen=at(second).isoformat())
            geo=snapshot_payload(update.snapshot)["devices"][0]["geographic_position"]
            self.assertEqual(geo["geographic_confidence"],expected)
            self.assertEqual(geo["owner_location_confidence"],"not_established_by_gps")
            self.assertEqual(self.runtime.gps_status_payload()[0]["geographic_confidence"],expected)
            self.assertFalse(update.snapshot.area_occupancies or update.detections)
        self.second=35;self.runtime.refresh()
        self.assertEqual(self.runtime.gps_status_payload()[0]["geographic_confidence"],"unknown")
        self.setUp();self.gps("not_home",gps_accuracy=5)
        self.assertEqual(self.runtime.snapshot.devices[0].geographic_position.geographic_quality,Quality.MEDIUM)

    def test_accuracy_calibration_and_missing_position_never_invent_an_exit(self):
        self.raw["sources"][0]["options"].update(timestamp_attribute="last_seen",high_accuracy_m=10,medium_accuracy_m=30)
        self.runtime=PresenceRuntime(parse_configuration(self.raw),now=lambda:at(self.second))
        self.gps("not_home",gps_accuracy=20,last_seen=at(1).isoformat())
        self.assertEqual(self.runtime.snapshot.devices[0].geographic_position.geographic_quality,Quality.MEDIUM)
        saved=self.runtime.export_state()
        self.raw["sources"][0]["options"]["high_accuracy_m"]=25
        self.runtime=PresenceRuntime(parse_configuration(self.raw),now=lambda:at(self.second))
        self.runtime.restore_state(saved)
        self.assertFalse(self.runtime.snapshot.devices)
        self.gps("not_home",second=2,gps_accuracy=20,last_seen=at(1).isoformat())
        self.assertEqual(self.runtime.snapshot.devices[0].geographic_position.geographic_quality,Quality.HIGH)
        update=self.deliver("device_tracker.phone","not_home",3,{})
        self.assertFalse(update.failures or update.snapshot.presences or update.snapshot.coverage_degraded)
        self.assertEqual(self.runtime.gps_status_payload()[0]["status"],"missing")
        for high,medium in ((0,200),(50,10),(True,200),(50,float("nan"))):
            self.raw["sources"][0]["options"].update(high_accuracy_m=high,medium_accuracy_m=medium)
            with self.assertRaises(ConfigurationError):parse_configuration(self.raw)

    def test_native_person_cannot_renew_or_duplicate_its_registered_gps_home(self):
        self.raw["sources"].append({"source_id":"home", "adapter":"person_home",
            "entity_ids":["person.owner"], "identity":"owner",
            "options":{"ignored_source_prefixes":["device_tracker.indoor_"]}})
        self.runtime=PresenceRuntime(parse_configuration(self.raw),now=lambda:at(self.second))
        self.deliver("person.owner","home",1,{"source":"device_tracker.phone"})
        self.assertFalse(self.runtime.snapshot.presences)
        update=self.gps(second=2)
        self.assertEqual((update.snapshot.count_minimum,update.snapshot.count_maximum),(0,1))
        self.assertEqual(update.snapshot.presences[0].source_ids,("gps",))
        self.deliver("person.owner","home",20,{"source":"device_tracker.phone"})
        self.assertEqual(self.runtime.next_expiration(),at(32))
        self.second=32; update=self.runtime.refresh()
        self.assertFalse(update.snapshot.presences or update.snapshot.devices or update.snapshot.coverage_degraded)
        self.deliver("person.owner","home",40,{"source":"device_tracker.phone"})
        self.assertFalse(self.runtime.snapshot.presences)
        self.gps("not_home",second=41)
        self.assertFalse(self.runtime.snapshot.presences)
        self.assertEqual(self.runtime.snapshot.devices[0].geographic_position.native_zone,"not_home")
        self.runtime._store.upsert(observation("face",identity_claim=identity("owner",42),location=area("beta",42)))
        self.second=42; self.runtime._snapshot=self.runtime._resolve_snapshot()
        self.assertEqual(self.runtime.snapshot.presences[0].location.area,"beta")
        self.assertEqual((self.runtime.snapshot.count_minimum,self.runtime.snapshot.count_maximum),(1,1))
        self.assertFalse(self.runtime.failures)

    def test_native_person_non_gps_origin_and_unregistered_channels_remain_usable(self):
        self.raw["sources"].append({"source_id":"home", "adapter":"person_home",
            "entity_ids":["person.owner"], "identity":"owner"})
        for changes in ({}, {"enabled":False}, {"identity":"someone_else"}):
            with self.subTest(changes=changes):
                raw=config();raw["sources"][0].update(changes)
                raw["sources"].append(self.raw["sources"][-1])
                self.runtime=PresenceRuntime(parse_configuration(raw),now=lambda:at(self.second))
                self.deliver("person.owner","home",1,{"source":"device_tracker.watch"})
                self.assertEqual(self.runtime.snapshot.presences[0].identity,"owner")
                self.deliver("person.owner","home",2,{"source":"device_tracker.phone"})
                self.assertEqual(bool(self.runtime.snapshot.presences),bool(changes))

    def test_restore_requalifies_native_person_origin_without_renewing_saved_fix(self):
        self.raw["sources"].append({"source_id":"home", "adapter":"person_home",
            "entity_ids":["person.owner"], "identity":"owner"})
        self.runtime=PresenceRuntime(parse_configuration(self.raw),now=lambda:at(self.second))
        self.deliver("person.owner","home",1,{"source":"device_tracker.watch"})
        self.gps(second=2)
        saved=self.runtime.export_state()
        self.second=40
        self.runtime=PresenceRuntime(parse_configuration(self.raw),now=lambda:at(self.second))
        self.runtime.restore_state(saved)
        self.assertFalse(self.runtime.snapshot.presences or self.runtime.snapshot.devices)
        self.deliver("person.owner","home",41,{"source":"device_tracker.phone"})
        self.assertFalse(self.runtime.snapshot.presences)
        self.deliver("person.owner","home",42,{"source":"device_tracker.watch"})
        self.assertEqual(self.runtime.snapshot.presences[0].identity,"owner")

    def test_direct_gps_home_keeps_weak_ble_room_without_inventing_a_body(self):
        self.raw["sources"].extend([
            {"source_id":"home", "adapter":"person_home", "entity_ids":["person.owner"], "identity":"owner"},
            {"source_id":"ble", "adapter":"bermuda_area", "entity_ids":["sensor.area"], "identity":"owner",
             "spatial_quality":"medium", "options":{"target_id":"phone"}},
            {"source_id":"range", "adapter":"bermuda_signal", "area":"alpha", "entity_ids":["sensor.range"],
             "identity":"owner", "options":{"device_id":"phone", "receiver_id":"alpha", "metric":"distance"}}])
        self.runtime=PresenceRuntime(parse_configuration(self.raw),now=lambda:at(self.second))
        self.deliver("person.owner","home",1,{"source":"device_tracker.phone"})
        self.gps(second=2)
        self.deliver("sensor.area","alpha",3)
        self.deliver("sensor.range","3.4",4,{"unit_of_measurement":"m"})
        update=self.deliver("sensor.range","3.2",5,{"unit_of_measurement":"m"})
        p,=update.snapshot.presences
        self.assertEqual((p.location.area,p.location.method,p.location_status,p.location.quality),
                         ("alpha","device_room_candidate","possible",Quality.LOW))
        self.assertEqual((update.snapshot.count_minimum,update.snapshot.count_maximum),(0,1))
        self.assertFalse(update.snapshot.area_occupancies or update.detections)


if __name__=="__main__":unittest.main()
