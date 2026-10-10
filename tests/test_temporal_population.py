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
        previous = self.resolve(self.device(), observation("old-face", location=area("delta", -10),
                                identity_claim=identity(seconds=-10)))
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

    def test_animal_and_adjacent_radar_do_not_prove_a_third_individual(self):
        person=observation("face", location=area("delta",-10), identity_claim=identity(seconds=-10))
        dog=observation("dog",kind=TargetKind.ANIMAL,classification="dog",target_id="animal-a",
                        family="frigate_event",location=area("beta",-3.732))
        radar=observation("radar",kind=TargetKind.UNKNOWN_LIVING,family="mtr_count",
                          location=area("alpha"))
        for items in permutations((person,dog,radar)):
            result=self.resolve(*items)
            self.assertEqual((result.count_minimum,result.count_maximum),(2,3))
            unknown=next(p for p in result.presences if p.kind is TargetKind.UNKNOWN_LIVING)
            self.assertEqual(unknown.location_status,"possible")
            self.assertIsNone(unknown.classification)
            self.assertIsNone(unknown.identity)
            self.assertEqual(unknown.location.area,"alpha")
            self.assertEqual(len(result.area_occupancies),3,"all physical positives remain current")
        for location in (area("epsilon"),area("gamma",21),area("alpha",quality=Quality.LOW)):
            result=self.resolve(person,dog,replace(radar,location=location),second=max(0,(location.observed_at-at()).total_seconds()))
            self.assertEqual((result.count_minimum,result.count_maximum),(3,3))
        human=self.resolve(person,dog,replace(radar,target_kind=TargetKind.PERSON,target_id="visitor"))
        self.assertEqual((human.count_minimum,human.count_maximum),(3,3))
        stationary=self.resolve(person,replace(dog,location=area("alpha",-60)),radar)
        self.assertEqual((stationary.count_minimum,stationary.count_maximum),(2,3))
        buckets=self.resolve(person,dog,replace(radar,source=replace(radar.source,source_id="one-radar")),
            observation("second-bucket",source_id="one-radar",family="mtr_count",
                        kind=TargetKind.UNKNOWN_LIVING,location=area("gamma")))
        self.assertEqual((buckets.count_minimum,buckets.count_maximum),(3,4),
                         "one animal cannot consume two disjoint buckets of one radar")

    def test_area_support_uses_independent_families_not_channel_count(self):
        visual=observation("object",family="frigate_event",target_id="body-a",location=area("alpha"))
        face=replace(visual,observation_id="face",source=replace(visual.source,source_id="face",family="frigate_face"))
        radar=observation("radar",family="mtr_count",kind=TargetKind.UNKNOWN_LIVING,location=area("alpha"))
        weak=observation("weak",family="context",kind=TargetKind.UNKNOWN_LIVING,
                         location=area("alpha",quality=Quality.LOW))
        result=self.resolve(visual,face,radar,weak)
        public=public_presence_projection(result)["active_areas"][0]
        self.assertEqual(public["current_source_families"],["physical_presence","visual"])
        self.assertEqual(public["current_location_confidence"],"high")
        self.assertEqual((result.count_minimum,result.count_maximum),(1,1))
        stale=replace(radar,location=area("alpha",-30))
        public=public_presence_projection(self.resolve(visual,stale))["active_areas"][0]
        self.assertEqual(public["current_source_families"],["visual"],"old measurement does not boost confidence")
        dependent=replace(radar,source=replace(radar.source,dependency_group="shared-camera"))
        linked=replace(visual,source=replace(visual.source,dependency_group="shared-camera"))
        public=public_presence_projection(self.resolve(linked,dependent))["active_areas"][0]
        self.assertEqual(len(public["current_source_families"]),1,"explicit dependency is one family vote")

    def test_device_support_requires_current_owner_association(self):
        device=replace(self.device("alpha",0),source=replace(self.device().source,family="bermuda_area"))
        radar=observation("radar",family="binary_presence",kind=TargetKind.UNKNOWN_LIVING,location=area("alpha"))
        result=self.resolve(device,radar)
        self.assertEqual(public_presence_projection(result)["active_areas"][0]["current_source_families"],
                         ["physical_presence"])
        face=observation("face",family="frigate_event",target_id="body-a",location=area("alpha"),identity_claim=identity())
        associated=self.resolve(device,radar,face)
        self.assertEqual(public_presence_projection(associated)["active_areas"][0]["current_source_families"],
                         ["bermuda_area","physical_presence","visual"])
        dog=observation("dog",family="frigate_event",kind=TargetKind.ANIMAL,classification="dog",
                        target_id="animal-a",location=area("alpha"))
        result=self.resolve(device,dog)
        self.assertEqual(public_presence_projection(result)["active_areas"][0]["current_source_families"],["visual"])
        self.assertEqual(next(p for p in result.presences if p.identity).location.level.value,"home")

    def test_recognized_body_keeps_visual_support_without_anonymous_population(self):
        face=observation("face",family="resolved_event",target_id="body-a",
                         location=area("alpha",-.7),identity_claim=identity(seconds=-.7))
        radar=observation("radar",family="mtr_count",kind=TargetKind.UNKNOWN_LIVING,
                          location=area("beta",-1.4))
        result=self.resolve(face,radar)
        public={a["area"]:a for a in public_presence_projection(result)["active_areas"]}
        self.assertEqual(public["alpha"]["current_source_families"],["visual"])
        self.assertEqual(public["alpha"]["current_location_confidence"],"high")
        self.assertEqual(public["beta"]["current_source_families"],["physical_presence"])
        self.assertEqual((result.count_minimum,result.count_maximum),(1,2))
        self.assertEqual(next(p for p in result.presences if p.identity).location.area,"alpha")

    def test_recognized_support_deduplicates_channels_and_retires_with_body(self):
        face=observation("face",family="frigate_face",location=area("alpha"),identity_claim=identity())
        alias=replace(face,observation_id="object",source=replace(face.source,source_id="object",family="frigate_event"))
        radar=observation("radar",family="mtr_count",kind=TargetKind.UNKNOWN_LIVING,location=area("alpha"))
        for items,families in (((face,alias),["visual"]),((face,alias,radar),["physical_presence","visual"])):
            result=self.resolve(*items)
            public=public_presence_projection(result)["active_areas"][0]
            self.assertEqual(public["current_source_families"],families)
            self.assertEqual(public["maximum_count"],1)
            self.assertEqual((result.count_minimum,result.count_maximum),(1,1))
        other=replace(face,observation_id="other",identity=identity("person_b"))
        result=self.resolve(face,other)
        self.assertEqual((result.count_minimum,result.count_maximum),(2,2))
        self.assertEqual(public_presence_projection(result)["active_areas"][0]["maximum_count"],2)
        previous=self.resolve(face)
        for items in ((self.device("alpha",1),),
                      (self.device("alpha",1),replace(face,location=area("beta",-1)) )):
            result=self.resolve(*items,previous=previous,second=1)
            self.assertEqual(result.area_occupancies,(),"continuity and superseded bodies are not current support")
        self.assertEqual(self.resolve(replace(face,location=floor())).area_occupancies,())


if __name__ == "__main__":
    unittest.main()
