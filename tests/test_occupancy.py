from __future__ import annotations

from copy import deepcopy
import json
from pathlib import Path
import unittest

from presence_engine.adapters import AdapterEnvelope
from presence_engine.configuration import parse_configuration
from presence_engine.engine import FrozenClock, PresenceConfig, PresenceResolver, TargetKind
from presence_engine.projection import snapshot_payload
from presence_engine.public_projection import identity_projection, public_presence_projection
from presence_engine.runtime import PresenceRuntime
from helpers import area, at, identity, observation
import test_replay_fixtures


class OccupancyTests(unittest.TestCase):
    def setUp(self):
        self.fixture = json.loads((Path(__file__).parent / "fixtures" /
                                   "held-radar-after-visual-end.json").read_text(encoding="utf-8"))
        self.now = at(0)
        self.runtime = PresenceRuntime(parse_configuration(self.fixture["configuration"]),
                                       now=lambda: self.now)

    def deliver(self, step):
        self.now = at(step["at"])
        return self.runtime.process(AdapterEnvelope(
            step["channel_type"], step["channel"], test_replay_fixtures.ReplayFixtureTests._payload(step["payload"]),
            self.now, self.now,
        ))

    def seed_held_radar(self):
        for step in self.fixture["steps"][:7]:
            self.deliver(step)

    def test_held_radar_survives_visual_end_without_renewing_identity_or_location(self):
        self.seed_held_radar()
        snapshot = self.runtime.snapshot
        public = public_presence_projection(snapshot)
        area_result = public["active_areas"][0]
        person = snapshot.presences[0]
        self.assertEqual(area_result["current_minimum_count"], 1)
        self.assertEqual(area_result["last_current_observed_at"], at(1).isoformat())
        self.assertEqual(person.location_status, "continued")
        self.assertEqual(person.location.observed_at, at(2))
        self.assertEqual(identity_projection(snapshot, "person_a")["identity_observed_at"],
                         at(0).isoformat())
        self.assertEqual((snapshot.count_minimum, snapshot.count_maximum), (1, 1))
        self.assertEqual(snapshot_payload(snapshot)["area_occupancies"][0]["source_ids"], ["radar"])

    def test_radar_zero_clears_current_occupancy_but_not_historical_location(self):
        self.seed_held_radar()
        for step in self.fixture["steps"][7:]:
            self.deliver(step)
        public = public_presence_projection(self.runtime.snapshot)
        self.assertEqual(public["active_areas"], [])
        self.assertEqual(self.runtime.snapshot.area_occupancies, ())
        person = self.runtime.snapshot.presences[0]
        self.assertIsNone(person.location.area)
        self.assertEqual(person.last_location.area, "alpha")

    def test_unavailable_radar_removes_occupancy(self):
        self.seed_held_radar()
        self.deliver({"at": 4, "channel_type": "state", "channel": "sensor.total",
                      "payload": {"state": "unavailable"}})
        self.assertEqual(self.runtime.snapshot.area_occupancies, ())
        self.assertEqual(public_presence_projection(self.runtime.snapshot)["active_areas"][0]
                         ["current_minimum_count"], 0)

    def test_source_expiration_is_not_extended_by_person_continuity(self):
        configuration = deepcopy(self.fixture["configuration"])
        configuration["sources"][1]["expires_after_seconds"] = 5
        self.runtime = PresenceRuntime(parse_configuration(configuration), now=lambda: self.now)
        self.seed_held_radar()
        self.now = at(7)
        self.runtime.refresh()
        self.assertEqual(self.runtime.snapshot.area_occupancies, ())
        self.assertFalse(any(area["current_minimum_count"] for area in
                             public_presence_projection(self.runtime.snapshot)["active_areas"]))

    def test_occupancy_rebuilds_after_restart_and_does_not_add_a_person(self):
        self.seed_held_radar()
        before=public_presence_projection(self.runtime.snapshot)["active_areas"][0]
        saved = self.runtime.export_state()
        self.runtime = PresenceRuntime(parse_configuration(self.fixture["configuration"]),
                                       now=lambda: self.now)
        self.runtime.restore_state(saved)
        self.assertEqual(public_presence_projection(self.runtime.snapshot)["active_areas"][0]
                         ["current_minimum_count"], 1)
        self.assertEqual(len(self.runtime.snapshot.presences), 1)
        after=public_presence_projection(self.runtime.snapshot)["active_areas"][0]
        self.assertEqual(after["current_source_families"],before["current_source_families"])
        self.assertEqual(after["current_location_confidence"],before["current_location_confidence"])

    def test_registered_device_alone_never_creates_area_occupancy(self):
        self.deliver(self.fixture["steps"][0])
        self.assertEqual(public_presence_projection(self.runtime.snapshot)["active_areas"], [])
        self.assertEqual(self.runtime.snapshot.area_occupancies, ())

    def test_occupancy_contract_rejects_floor_or_empty_population(self):
        from presence_engine.engine import AreaOccupancy, CountClaim
        from helpers import floor
        for location, count in ((floor(), CountClaim(1, 1, at(), True)),
                                (area("alpha"), CountClaim(0, 0, at(), True))):
            with self.subTest(location=location.level, maximum=count.maximum):
                with self.assertRaises(ValueError):
                    AreaOccupancy(location, count, ("source",))

    def test_possible_physical_evidence_is_not_confirmed_area_occupancy(self):
        from presence_engine.engine import CountClaim
        resolver = PresenceResolver(PresenceConfig(), FrozenClock(at(0)))
        result = resolver.resolve([observation(
            "possible", location=area("alpha"),
            count=CountClaim(0, 1, at(0), True),
        )], revision=1)
        self.assertEqual(public_presence_projection(result)["active_areas"][0]
                         ["current_minimum_count"], 0)

    def test_current_body_elsewhere_does_not_disappear_or_move_identity_to_held_radar(self):
        resolver = PresenceResolver(PresenceConfig(), FrozenClock(at(0)))
        result = resolver.resolve([
            observation("radar", kind=TargetKind.UNKNOWN_LIVING, location=area("alpha", -30)),
            observation("face", location=area("delta", 0), identity_claim=identity()),
        ], revision=1)
        person = next(item for item in result.presences if item.identity)
        self.assertEqual(person.location.area, "delta")
        self.assertTrue(any(area["area"] == "alpha" and area["current_minimum_count"] == 1
                            for area in public_presence_projection(result)["active_areas"]))


if __name__ == "__main__":
    unittest.main()
