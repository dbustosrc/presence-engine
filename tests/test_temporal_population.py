"""Room transitions must not rewind paths or prove independent occupants."""

from dataclasses import replace
from itertools import permutations
import unittest

from presence_engine.engine import CountClaim, FrozenClock, PresenceConfig, PresenceResolver, Quality, TargetKind
from presence_engine.public_projection import public_presence_projection
from helpers import area, at, floor, identity, observation


class TemporalPopulationTests(unittest.TestCase):
    def setUp(self):
        self.config = PresenceConfig(
            area_floors={"alpha": "floor_alpha", "beta": "floor_alpha", "gamma": "floor_alpha", "delta": "floor_beta"},
            adjacency={"alpha": frozenset({"beta"}), "beta": frozenset({"alpha", "gamma"})},
        )

    def resolve(self, *items, previous=None, second=0):
        return PresenceResolver(self.config, FrozenClock(at(second))).resolve(
            items, revision=7, previous=previous)

    def device(self, room="delta", second=-30):
        return observation("device", kind=TargetKind.DEVICE, location=area(room, second),
                           identity_claim=identity(seconds=second, method="registered_owner"))

    def test_older_adjacent_measurement_does_not_rewind_person(self):
        person = observation("face", location=area("beta", -1), identity_claim=identity(seconds=-1))
        older = observation("radar", kind=TargetKind.UNKNOWN_LIVING, location=area("alpha", -2))
        result = self.resolve(person, older)
        known = next(p for p in result.presences if p.identity)
        self.assertEqual(known.location.area, "beta")
        self.assertEqual(known.location.observed_at, at(-1))
        self.assertEqual((result.count_minimum, result.count_maximum), (1, 2))

    def test_previous_direct_room_supersedes_older_visual_inference_for_control(self):
        previous = self.resolve(self.device(), observation("visual-new", target_id="target-new",
                                location=area("beta", -1), identity_claim=identity(seconds=-1)))
        inferred = observation("visual-old", target_id="target-old",
                               location=area("alpha", -2, quality=Quality.MEDIUM, method="ptz_profile_fallback"))
        radar = observation("radar-beta", kind=TargetKind.UNKNOWN_LIVING, location=area("beta", -3))
        result = self.resolve(self.device(), inferred, radar, previous=previous)
        known = next(p for p in result.presences if p.identity)
        self.assertEqual(known.location.area, "beta")
        self.assertEqual(known.location.observed_at, at(-1))
        public = public_presence_projection(result)
        self.assertNotIn("alpha", {a["area"] for a in public["active_areas"] if a["current_minimum_count"]})
        self.assertTrue(any(p.location and p.location.floor == "floor_alpha" and not p.location.area
                            for p in result.presences if not p.identity))
        self.assertEqual(inferred.location.area, "alpha", "historical observation stays intact")

    def test_continuity_and_adjacent_populations_are_not_four_exact_individuals(self):
        previous = self.resolve(self.device(), observation("old-radar", kind=TargetKind.UNKNOWN_LIVING,
                                location=area("delta", -10)))
        items = (self.device(), observation("visual", target_id="body-a", location=area("alpha", -3)),
                 observation("radar-beta", kind=TargetKind.UNKNOWN_LIVING, location=area("beta", -2)),
                 observation("radar-gamma", kind=TargetKind.UNKNOWN_LIVING, location=area("gamma", -1)))
        for ordered in permutations(items):
            result = self.resolve(*ordered, previous=previous)
            self.assertEqual((result.count_minimum, result.count_maximum), (1, 4))
            self.assertEqual(len(result.presences), 4, "do not delete evidence or possible visitors")
            self.assertIn("cross_area_population_overlap", result.reasons)
        transition = replace(items[1], location=floor(-3))
        result = self.resolve(items[0], transition, *items[2:], previous=previous)
        self.assertEqual((result.count_minimum, result.count_maximum), (1, 4))

    def test_late_identity_refinement_does_not_rewind_a_newer_person_path(self):
        previous = self.resolve(self.device(), observation("new", target_id="new-body",
                                location=area("beta", -1), identity_claim=identity(seconds=-1)))
        late = observation("old", target_id="old-body",
                           location=area("alpha", -2, quality=Quality.MEDIUM),
                           identity_claim=identity(seconds=0))
        result = self.resolve(self.device(), late, previous=previous)
        known = next(p for p in result.presences if p.identity)
        self.assertEqual(known.location.area, "beta")
        self.assertEqual(known.identity_observed_at, at(0))

    def test_independent_rooms_and_distinct_visual_targets_keep_lower_bounds(self):
        first = observation("visual-a", target_id="body-a", location=area("alpha", -1))
        second = observation("visual-b", target_id="body-b", location=area("beta", 0))
        aggregate = observation("radar", kind=TargetKind.UNKNOWN_LIVING, location=area("gamma", 0))
        result = self.resolve(first, second, aggregate)
        self.assertEqual((result.count_minimum, result.count_maximum), (2, 3))
        independent = self.resolve(first, replace(aggregate, location=area("delta", 0)))
        self.assertEqual((independent.count_minimum, independent.count_maximum), (2, 2))
        buckets=self.resolve(
            observation("zone-a",source_id="radar",kind=TargetKind.UNKNOWN_LIVING,location=area("alpha")),
            observation("outside",source_id="radar",kind=TargetKind.UNKNOWN_LIVING,location=floor()),
        )
        self.assertEqual((buckets.count_minimum,buckets.count_maximum),(2,2),
                         "partitioned buckets of one source are independent")

    def test_newer_visual_and_old_inference_without_recent_conflict_remain_available(self):
        previous = self.resolve(observation("face", location=area("beta", -1), identity_claim=identity(seconds=-1)))
        fresh = observation("new", target_id="body-a", location=area("alpha", 0))
        result = self.resolve(observation("old-face", location=area("beta", -1), identity_claim=identity(seconds=-1)), fresh,
                              previous=previous)
        self.assertEqual(next(p for p in result.presences if p.identity).location.area, "alpha")
        inferred = replace(fresh, location=area("alpha", 25, quality=Quality.MEDIUM, method="ptz_profile_fallback"))
        result = self.resolve(inferred, previous=previous, second=25)
        self.assertEqual(result.presences[0].location.area, "alpha")
        animal=replace(inferred,target_kind=TargetKind.ANIMAL,classification="dog",
                       location=area("alpha",-2,quality=Quality.MEDIUM,method="ptz_profile_fallback"))
        result=self.resolve(animal,previous=previous)
        self.assertEqual(result.presences[0].location.area,"alpha",
                         "another person's path does not relocate the animal")


if __name__ == "__main__":
    unittest.main()
