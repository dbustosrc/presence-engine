"""Device/body alternatives are explicit, never an exact identity or count."""

from dataclasses import replace
import unittest

from presence_engine.engine import (CountClaim, DeviceState, FrozenClock, PresenceConfig,
    PresenceResolver, Quality, TargetKind)
from presence_engine.projection import snapshot_payload
from presence_engine.public_projection import public_presence_projection
from helpers import area, at, identity, observation


class DeviceBodyOverlapTests(unittest.TestCase):
    def scene(self, *, people=("person_a",), count=1, body_area="alpha", pet=False,
              visual=False, unavailable=(), body_quality=Quality.HIGH, face=False):
        observations = [observation("home_"+name, kind=TargetKind.DEVICE, family="bermuda_area",
            identity_claim=identity(name), target_id="phone_"+name, location=area("alpha")) for name in people]
        body = observation("radar", family="frigate_event" if visual else "binary_presence",
            kind=TargetKind.PERSON if visual else TargetKind.UNKNOWN_LIVING,
            source_id="radar", location=area(body_area, 2, quality=body_quality),
            count=CountClaim(count, count, at(2), True, Quality.HIGH),
            target_id="visual_track" if visual else None, detected=2, received=2)
        observations.append(body)
        if pet:
            observations.append(observation("pet", kind=TargetKind.ANIMAL, classification="dog",
                location=area(body_area, 2), count=CountClaim(1, 1, at(2), True, Quality.HIGH)))
        if face:
            observations.append(observation("face", identity_claim=identity(people[0], 2),
                location=area("beta", 2), detected=2, received=2))
        hints = tuple(DeviceState("phone_"+name, name,
            area("alpha", 1, method="device_room_candidate", quality=Quality.LOW),
            ("home_"+name, "distance")) for name in people)
        return PresenceResolver(PresenceConfig(), FrozenClock(at(3))).resolve(
            observations, revision=1, device_room_candidates=hints, unavailable_sources=unavailable)

    def test_single_owner_alternative_groups_display_not_identity_or_count(self):
        snapshot = self.scene()
        body = next(p for p in snapshot.presences if not p.identity)
        self.assertEqual(body.possible_identity_ids, ("person_a",))
        self.assertIsNone(body.identity)
        self.assertEqual(body.identity_quality, Quality.UNKNOWN)
        owner = next(p for p in snapshot.presences if p.identity)
        self.assertEqual(owner.location.observed_at, at(1))
        self.assertNotIn("radar", owner.location_source_ids)
        self.assertEqual((snapshot.count_minimum, snapshot.count_maximum), (1, 2))
        public = public_presence_projection(snapshot)
        self.assertEqual(len(public["presences"]), 2)
        self.assertEqual(len(public["display_presences"]), 1)
        self.assertEqual(public["display_presences"][0]["compatible_body_evidence"][0]["location_sources"], ["radar"])
        self.assertEqual(public["count_estimate"]["maximum"], 2)
        raw = snapshot_payload(snapshot)
        self.assertEqual(next(p for p in raw["presences"] if not p["identity"])["possible_identity_ids"], ["person_a"])

    def test_multiple_owners_remain_alternatives_not_an_arbitrary_match(self):
        snapshot = self.scene(people=("person_a", "person_b"))
        body = next(p for p in snapshot.presences if not p.identity)
        self.assertEqual(body.possible_identity_ids, ("person_a", "person_b"))
        self.assertEqual(len(public_presence_projection(snapshot)["display_presences"]), 3)

    def test_separation_animals_distinct_tracks_and_multiple_bodies_are_not_nested(self):
        for options in ({"body_area": "beta"}, {"pet": True}, {"visual": True},
                        {"count": 2}, {"unavailable": ("radar",)},
                        {"body_quality": Quality.LOW}, {"face": True}):
            with self.subTest(options=options):
                snapshot = self.scene(**options)
                self.assertFalse(any(p.possible_identity_ids for p in snapshot.presences))
                self.assertEqual(len(public_presence_projection(snapshot)["display_presences"]), len(snapshot.presences))

    def test_left_behind_phone_is_only_an_alternative_not_proof_of_owner(self):
        # The same measurements can be a visitor beside an abandoned phone.
        snapshot = self.scene()
        self.assertEqual((snapshot.count_minimum, snapshot.count_maximum), (1, 2))
        body = next(p for p in snapshot.presences if not p.identity)
        self.assertIsNone(body.identity_observed_at)
        with self.assertRaises(ValueError):
            replace(body, identity="person_a")
