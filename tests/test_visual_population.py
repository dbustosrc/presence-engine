"""A local object ID is not a globally independent body or identity."""

from dataclasses import replace
from itertools import permutations
import unittest

from helpers import area, at, identity, observation
from presence_engine.engine import CountClaim, FrozenClock, PresenceConfig, PresenceResolver, Quality, ObservationStatus, SpatialClaim, SpatialLevel, TargetKind
from presence_engine.public_projection import public_presence_projection


def body(key, camera, *, kind=TargetKind.PERSON, room="alpha", second=0, owner=None):
    item = observation(key, target_id=key, kind=kind, family="frigate_event",
        classification="dog" if kind is TargetKind.ANIMAL else "person",
        location=area(room, second), identity_claim=identity(owner, seconds=second) if owner else None)
    return replace(item, source=replace(item.source, native_id=camera, coverage_group="camera:" + camera))


class VisualPopulationTests(unittest.TestCase):
    def resolve(self, *items):
        return PresenceResolver(PresenceConfig(area_floors={"alpha":"floor_alpha", "delta":"floor_beta"}),
            FrozenClock(at())).resolve(items, revision=1)

    def test_one_owner_cannot_consume_two_local_targets(self):
        known = observation("face", family="resolved_event", identity_claim=identity(), location=area("alpha"))
        items = (known, body("object_a", "camera_a"), body("object_b", "camera_a"))
        for ordered in permutations(items):
            result = self.resolve(*ordered)
            self.assertEqual((result.count_minimum,result.count_maximum), (2,3))
            self.assertTrue(any(p.identity is None and p.kind is TargetKind.PERSON for p in result.presences))

    def test_identified_object_and_different_object_in_same_camera_are_distinct(self):
        known = body("owner_object", "camera_a", owner="person_a")
        visitor = body("visitor_object", "camera_a")
        result = self.resolve(known, visitor)
        self.assertEqual((result.count_minimum, result.count_maximum), (2, 2))
        self.assertEqual(next(p for p in result.presences if p.identity is None).hypothesis_id, "target:visitor_object:1")
        self.assertEqual(public_presence_projection(result)["active_areas"][0]["current_minimum_count"], 2)
        alias = replace(known, identity=None, observation_id="object_alias")
        result = self.resolve(known, alias, visitor)
        self.assertEqual((result.count_minimum, result.count_maximum), (2, 2))

    def test_same_room_cross_camera_targets_are_possible_overlap_not_exact_duplicates(self):
        for kind in (TargetKind.PERSON, TargetKind.ANIMAL):
            first = body("object_a", "camera_a", kind=kind)
            second = body("object_b", "camera_b", kind=kind)
            result = self.resolve(first, second)
            self.assertEqual((result.count_minimum, result.count_maximum), (1, 2))
            self.assertEqual(set(source for p in result.presences for source in p.source_ids),
                             {first.source.source_id, second.source.source_id})
            self.assertTrue(any(p.location_status == "possible" for p in result.presences))
            local = self.resolve(first, replace(second, source=replace(second.source,
                native_id="camera_a", coverage_group="camera:camera_a")))
            self.assertEqual((local.count_minimum, local.count_maximum), (2, 2))

    def test_overlap_does_not_merge_species_or_rooms_and_lifecycle_retires_it(self):
        dog = body("dog_a", "camera_a", kind=TargetKind.ANIMAL)
        for other in (body("person_b", "camera_b"),
                      body("dog_b", "camera_b", kind=TargetKind.ANIMAL, room="delta"),
                      replace(body("cat_b", "camera_b", kind=TargetKind.ANIMAL), classification="cat")):
            self.assertEqual((self.resolve(dog, other).count_minimum, self.resolve(dog, other).count_maximum), (2, 2))
        stationary=body("dog_old", "camera_b", kind=TargetKind.ANIMAL, second=-300)
        self.assertEqual((self.resolve(dog,stationary).count_minimum,self.resolve(dog,stationary).count_maximum),(1,2))
        person=body("person_now", "camera_a")
        old_person=body("person_old", "camera_b", second=-300)
        self.assertEqual((self.resolve(person,old_person).count_minimum,self.resolve(person,old_person).count_maximum),(1,2))
        ended=replace(stationary,status=ObservationStatus.ENDED,ended_at=at())
        self.assertEqual((self.resolve(dog,ended).count_minimum,self.resolve(dog,ended).count_maximum),(1,1))
        left = body("left", "camera_a")
        right = body("right", "camera_a")
        another_view = body("other", "camera_b")
        result = self.resolve(left, right, another_view)
        self.assertEqual((result.count_minimum, result.count_maximum), (2, 3))

    def test_home_identity_is_not_an_extra_exact_body(self):
        home = observation("home", family="person_home", identity_claim=identity(method="home_scope"),
                           location=SpatialClaim(SpatialLevel.HOME, at(), quality=Quality.LOW))
        visitor = body("anonymous", "camera_a")
        result = self.resolve(home, visitor)
        self.assertEqual((result.count_minimum, result.count_maximum), (1, 2))
        self.assertEqual(next(p for p in result.presences if p.identity).location.level, SpatialLevel.HOME)

    def test_physical_count_survives_uncertain_cross_camera_overlap(self):
        first = body("first", "camera_a")
        second = body("second", "camera_b")
        radar = observation("radar", kind=TargetKind.UNKNOWN_LIVING, family="mtr_count",
            location=area("alpha"), count=CountClaim(2,2,at(),True))
        for ordered in permutations((first, second, radar)):
            result = self.resolve(*ordered)
            self.assertEqual((result.count_minimum,result.count_maximum),(2,3))
            self.assertEqual(public_presence_projection(result)["active_areas"][0]["minimum_count"],2)
        known = body("first", "camera_a", owner="person_a")
        third = body("third", "camera_a")
        radar = replace(radar,count=CountClaim(3,3,at(),True))
        result = self.resolve(known, third, radar)
        self.assertEqual((result.count_minimum,result.count_maximum),(3,3))

    def test_unknown_observer_and_scope_do_not_invent_overlap(self):
        first = body("first", "camera_a")
        second = body("second", "camera_b")
        for item in (replace(second,source=replace(second.source,native_id=None,coverage_group=None)),
                     replace(second,location=replace(second.location,area=None,level=SpatialLevel.FLOOR))):
            result = self.resolve(first,item)
            self.assertEqual((result.count_minimum,result.count_maximum),(2,2))

    def test_overlap_never_erases_frames_or_changes_identity_confidence(self):
        known = body("known", "camera_a", owner="person_a")
        visitor = body("visitor", "camera_a")
        other_view = body("other", "camera_b")
        items=(known,visitor,other_view)
        results=[self.resolve(*ordered) for ordered in permutations(items)]
        self.assertTrue(all(r == results[0] for r in results))
        result=results[0]
        self.assertEqual((result.count_minimum,result.count_maximum),(2,3))
        self.assertEqual(next(p for p in result.presences if p.identity).identity_quality,Quality.HIGH)
        self.assertTrue(any(p.hypothesis_id == "target:visitor:1" for p in result.presences))
        self.assertEqual(visitor.identity,None)
        self.assertIn("cross_camera_population_overlap",result.reasons)


if __name__ == "__main__":
    unittest.main()
