"""A detector clearing its own point is not an empty-room/home assertion."""

from dataclasses import replace
import unittest

from presence_engine.adapters import AdapterEnvelope, EntityStateAdapter, MTRCountAdapter
from presence_engine.configuration import parse_configuration
from presence_engine.engine import (CountClaim, FrozenClock, ObservationStatus, PresenceConfig,
    PresenceResolver, Quality, TargetKind)
from presence_engine.runtime import PresenceRuntime
from helpers import at, area, identity, observation


def configuration(adapter="binary_presence"):
    return {"schema_version": 1, "areas": {"alpha": "ground", "beta": "ground"}, "sources": [
        {"source_id": "home", "adapter": "person_home", "entity_ids": ["person.owner"], "identity": "person_a"},
        {"source_id": "phone", "adapter": "bermuda_area", "entity_ids": ["sensor.phone_area"], "identity": "person_a",
         "spatial_quality": "medium", "options": {"area_map": {"Alpha": "alpha", "Beta": "beta"}}},
        {"source_id": "radar", "adapter": adapter, "entity_ids": ["binary_sensor.radar" if adapter == "binary_presence" else "sensor.count"],
         "area": "alpha", "spatial_quality": "high"}]}


class NegativeSupportTests(unittest.TestCase):
    def setUp(self):
        self.second = 0
        self.runtime = PresenceRuntime(parse_configuration(configuration()), now=lambda: at(self.second))

    def deliver(self, channel, state, second, observed=None):
        self.second = second
        return self.runtime.process(AdapterEnvelope("state", channel, {"state": state},
            at(second if observed is None else observed), at(second)))

    def seed(self):
        self.deliver("person.owner", "home", 0)
        self.deliver("sensor.phone_area", "Alpha", 1)
        self.deliver("binary_sensor.radar", "on", 2)
        face=observation("accepted-face",family="resolved_event",target_id="body-a",
            location=area("alpha",2),identity_claim=identity(seconds=2),received=2)
        self.runtime._store.upsert(face)
        self.runtime._snapshot=self.runtime._resolve_snapshot()
        self.second=3
        self.runtime._store.upsert(replace(face,status=ObservationStatus.ENDED,ended_at=at(3),received_at=at(3),
            count=CountClaim(0,0,at(3),True)))
        self.runtime._snapshot=self.runtime._resolve_snapshot()
        return self.runtime.snapshot

    def test_measured_clear_retires_room_not_owner_and_phone_does_not_move_body(self):
        self.assertEqual(self.seed().presences[0].location.area, "alpha")
        update = self.deliver("binary_sensor.radar", "off", 10)
        self.assertIn("previous_location_support_cleared", update.snapshot.reasons)
        self.assertEqual(update.snapshot.presences[0].location_status, "location_cleared")
        self.assertEqual(update.snapshot.presences[0].location.level.value, "home")
        self.assertEqual(update.snapshot.presences[0].last_location.area, "alpha")
        self.assertEqual(update.snapshot.presences[0].last_location.observed_at, at(2))
        self.assertEqual(update.snapshot.presences[0].location_clear_source_ids, ("radar",))
        self.assertEqual((update.snapshot.count_minimum, update.snapshot.count_maximum), (1, 1))
        self.assertFalse(update.snapshot.coverage_degraded)
        self.assertFalse(update.snapshot.area_occupancies)
        moved = self.deliver("sensor.phone_area", "Beta", 11).snapshot
        self.assertIsNone(moved.presences[0].location.area)
        self.assertEqual(moved.devices[0].location.area, "beta")
        self.assertEqual(moved.presences[0].last_location.area, "alpha")
        self.assertEqual(moved.presences[0].location_clear_source_ids, ("radar",))
        home = self.runtime._store.get("home", "home").observation
        phone = self.runtime._store.get("phone", "phone").observation
        arrived = PresenceResolver(self.runtime._resolver_config, FrozenClock(at(12))).resolve((home, phone,
            observation("new_radar", family="binary_presence", kind=TargetKind.UNKNOWN_LIVING,
                        location=area("beta", 12))), revision=5, previous=moved)
        owner=next(p for p in arrived.presences if p.identity)
        self.assertIsNone(owner.location.area)
        self.assertEqual(owner.last_location.area,"alpha")
        self.assertEqual(owner.location_clear_source_ids,("radar",))
        self.assertTrue(any(p.identity is None and p.location.area=="beta" for p in arrived.presences))
        self.assertEqual(self.runtime.next_expiration(), at(92))
        self.second = 92
        self.assertTrue(self.runtime.refresh().changed)
        self.assertIsNone(self.runtime.snapshot.presences[0].last_location)
        self.assertEqual(update.detections, ())
        saved = self.runtime.export_state()
        self.runtime = PresenceRuntime(parse_configuration(configuration()), now=lambda: at(self.second))
        self.runtime.restore_state(saved)
        self.assertIsNone(self.runtime.snapshot.presences[0].location.area)

    def test_unknown_unavailable_and_old_clear_do_not_assert_absence(self):
        for state in ("unknown", "unavailable"):
            self.setUp(); self.seed()
            snapshot = self.deliver("binary_sensor.radar", state, 10).snapshot
            self.assertEqual(snapshot.presences[0].location.area, "alpha")
            self.assertEqual(snapshot.presences[0].location_status, "continued")
            self.assertTrue(snapshot.coverage_degraded)
            self.assertNotIn("previous_location_support_cleared", snapshot.reasons)
        self.setUp(); self.seed()
        self.assertEqual(self.deliver("binary_sensor.radar", "off", 10, observed=1).snapshot.presences[0].location.area, "alpha")

    def test_clear_requires_own_source_area_scope_quality_and_measured_zero(self):
        prior = self.seed()
        home = self.runtime._store.get("home", "home").observation
        phone = self.runtime._store.get("phone", "phone").observation
        zero = observation("zero", source_id="radar", family="binary_presence", kind=TargetKind.UNKNOWN_LIVING,
            location=area("alpha", 10), count=CountClaim(0, 0, at(10), True),
            status=ObservationStatus.ENDED, ended=10, received=10)
        zero = replace(zero, source_diagnostics={"measured_clear": True})
        resolver = PresenceResolver(PresenceConfig(area_floors={"alpha": "ground", "beta": "ground"}), FrozenClock(at(10)))
        for variant in (
                replace(zero, source=replace(zero.source, source_id="another")),
                replace(zero, location=area("beta", 10)),
                replace(zero, location=area("alpha", 10, quality=Quality.LOW)),
                replace(zero, source_diagnostics={"measured_clear": False}),
                replace(zero, source=replace(zero.source, family="frigate_event")),
                replace(zero, count=CountClaim(0, 0, at(11), True)),
                replace(zero, location=area("alpha", 11)),
                replace(zero, target_kind=TargetKind.DEVICE),
                replace(zero, received_at=at(11))):
            result = resolver.resolve((home, phone, variant), revision=4, previous=prior)
            self.assertEqual(result.presences[0].location.area, "alpha")
        result = resolver.resolve((home, phone, zero), revision=4, previous=prior, unavailable_sources=("radar",))
        self.assertEqual(result.presences[0].location.area, "alpha")
        result = resolver.resolve((home, phone, zero), revision=4, previous=prior)
        self.assertIsNone(result.presences[0].location.area)

    def test_other_person_and_animal_do_not_maintain_owner_room_but_anonymous_person_can(self):
        prior = self.seed()
        home = self.runtime._store.get("home", "home").observation
        phone = self.runtime._store.get("phone", "phone").observation
        zero = EntityStateAdapter(self.runtime.configuration.sources[-1]).parse(
            AdapterEnvelope("state", "binary_sensor.radar", {"state": "off"}, at(10), at(10))).observations[0]
        resolver = PresenceResolver(PresenceConfig(area_floors={"alpha": "ground"}), FrozenClock(at(10)))
        for body in (observation("animal", kind=TargetKind.ANIMAL, classification="dog", location=area("alpha", 10)),
                     observation("visitor", identity_claim=identity("person_b", 10), location=area("alpha", 10))):
            result = resolver.resolve((home, phone, zero, body), revision=4, previous=prior)
            owner = next(p for p in result.presences if p.identity == "person_a")
            self.assertIsNone(owner.location.area)
            self.assertTrue(any(p.location and p.location.area == "alpha" for p in result.presences))
        for body in (observation("anonymous", location=area("alpha", 10)),
                     observation("owner", identity_claim=identity("person_a", 10), location=area("alpha", 10))):
            result = resolver.resolve((home, phone, zero, body), revision=4, previous=prior)
            owner = next(p for p in result.presences if p.identity == "person_a")
            self.assertEqual(owner.location.area, "alpha")

    def test_overlapping_mtr_zone_zeros_are_not_empty_zone_measurements(self):
        raw = {"schema_version": 1, "areas": {"alpha": "ground", "beta": "ground"}, "sources": [{
            "source_id": "mtr", "adapter": "mtr_count", "floor": "ground",
            "entity_ids": ["sensor.total", "sensor.a", "sensor.b"],
            "options": {"total_entity_id": "sensor.total", "zone_areas": {"sensor.a": "alpha", "sensor.b": "beta"}}}]}
        adapter = MTRCountAdapter(parse_configuration(raw).sources[0])
        for second, (channel, state) in enumerate((("sensor.total", "1"), ("sensor.a", "1"), ("sensor.b", "0"))):
            initial = adapter.parse(AdapterEnvelope("state", channel, {"state": state}, at(second), at(second)))
        clear_beta = next(o for o in initial.observations if o.location.area == "beta")
        self.assertTrue(clear_beta.source_diagnostics["measured_clear"])
        overlap = adapter.parse(AdapterEnvelope("state", "sensor.b", {"state": "1"}, at(3), at(3)))
        self.assertTrue(any(o.status is ObservationStatus.ACTIVE and o.location.area is None for o in overlap.observations))
        for item in overlap.observations:
            if item.location.area:
                self.assertFalse(item.source_diagnostics["measured_clear"])

    def test_fractional_negative_and_nonfinite_counts_never_become_zero_measurements(self):
        definition = parse_configuration(configuration("count")).sources[-1]
        for state in ("0.5", "-0.5", "-1", "nan", "inf"):
            with self.assertRaises(ValueError):
                EntityStateAdapter(definition).parse(AdapterEnvelope("state", "sensor.count", {"state": state}, at(1), at(1)))
        zero = EntityStateAdapter(definition).parse(AdapterEnvelope("state", "sensor.count", {"state": "0.0"}, at(1), at(1))).observations[0]
        self.assertTrue(zero.source_diagnostics["measured_clear"])
        self.assertTrue(zero.count.stable)


if __name__ == "__main__":
    unittest.main()
