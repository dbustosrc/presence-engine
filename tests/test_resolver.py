from __future__ import annotations

import unittest
from itertools import permutations

from presence_engine import (
    CONTRACT_VERSION,
    CountClaim,
    FrozenClock,
    PresenceConfig,
    PresenceHypothesis,
    PresenceResolver,
    PresenceSnapshot,
    Quality,
    TargetKind,
)

from helpers import area, at, floor, identity, observation


class ResolverTests(unittest.TestCase):
    def setUp(self) -> None:
        config=PresenceConfig(
            area_floors={"alpha":"floor_alpha","beta":"floor_alpha","gamma":"floor_alpha","delta":"floor_beta"},
            adjacency={
                "alpha":frozenset({"beta"}),
                "beta":frozenset({"alpha","gamma"}),
                "gamma":frozenset({"beta"}),
                "delta":frozenset(),
            },
        )
        self.resolver=PresenceResolver(config,FrozenClock(at(0)))

    def resolve(self,*items,previous=None,unavailable=()):
        return self.resolver.resolve(items,revision=7,previous=previous,unavailable_sources=unavailable)

    def test_stationary_device_does_not_duplicate_recognized_owner_elsewhere(self) -> None:
        device=observation(
            "device-a",family="proximity",kind=TargetKind.DEVICE,target_id="device-a",
            location=area("alpha",-30,quality=Quality.MEDIUM,method="nearest_receiver"),
            identity_claim=identity(seconds=-30,method="registered_owner"),
        )
        person=observation(
            "visual-a",kind=TargetKind.PERSON,target_id="target-a",location=area("beta",-1),
            identity_claim=identity(seconds=-1),event_id="event-a",
        )
        result=self.resolve(device,person)
        self.assertEqual((result.count_minimum,result.count_maximum),(1,1))
        self.assertEqual(result.presences[0].location.area,"beta")
        self.assertEqual(result.devices[0].location.area,"alpha")

    def test_stale_room_plus_new_adjacent_count_is_not_two_exact_people(self) -> None:
        device=observation(
            "device-a",kind=TargetKind.DEVICE,location=area("alpha",-30,quality=Quality.MEDIUM),
            identity_claim=identity(seconds=-30,method="registered_owner"),
        )
        count=observation(
            "count-b",kind=TargetKind.PERSON,location=area("beta",0),
            count=CountClaim(1,1,at(0),True),dependency_group="room-b",
        )
        result=self.resolve(device,count)
        self.assertEqual((result.count_minimum,result.count_maximum),(1,2))
        person=next(item for item in result.presences if item.identity == "person_a")
        self.assertEqual(person.location.area,"beta")
        self.assertEqual(person.location_status,"ambiguous_movement")

    def test_stale_device_does_not_hide_a_real_visitor(self) -> None:
        device=observation(
            "device-a",kind=TargetKind.DEVICE,location=area("alpha",-300,quality=Quality.MEDIUM),
            identity_claim=identity(seconds=-300,method="registered_owner"),
        )
        visitor=observation(
            "target-b",kind=TargetKind.PERSON,target_id="target-b",location=area("gamma",0),
        )
        result=self.resolve(device,visitor)
        self.assertEqual((result.count_minimum,result.count_maximum),(2,2))

    def test_floor_scope_identity_can_be_refined_by_current_area_evidence(self) -> None:
        person=observation(
            "visual-a",kind=TargetKind.PERSON,location=floor(-4),identity_claim=identity(seconds=-4),
        )
        area_evidence=observation(
            "target-a",kind=TargetKind.PERSON,target_id="target-a",location=area("alpha",0),
        )
        result=self.resolve(person,area_evidence)
        self.assertEqual((result.count_minimum,result.count_maximum),(1,1))
        self.assertEqual(result.presences[0].location.area,"alpha")

    def test_device_floor_scope_plus_area_evidence_keeps_visitor_uncertainty(self) -> None:
        device = observation(
            "device-a",
            kind=TargetKind.DEVICE,
            location=floor(-4),
            identity_claim=identity(seconds=-4, method="registered_owner"),
        )
        area_evidence = observation(
            "anonymous-a",
            kind=TargetKind.PERSON,
            location=area("alpha", 0),
        )

        result = self.resolve(device, area_evidence)

        self.assertEqual((result.count_minimum, result.count_maximum), (1, 2))
        self.assertIn("presence_count_is_an_interval", result.conflicts)

    def test_registered_device_corroborated_in_same_area_is_one_person(self) -> None:
        device = observation(
            "device-a",
            kind=TargetKind.DEVICE,
            location=area("alpha", -2, quality=Quality.MEDIUM),
            identity_claim=identity(seconds=-2, method="registered_owner"),
        )
        current_count = observation(
            "count-a",
            kind=TargetKind.PERSON,
            location=area("alpha", 0),
            count=CountClaim(1, 1, at(0), True),
            dependency_group="room-a",
        )

        result = self.resolve(device, current_count)

        self.assertEqual((result.count_minimum, result.count_maximum), (1, 1))

    def test_recognized_person_does_not_hide_nonadjacent_visitor(self) -> None:
        known = observation(
            "known-a",
            kind=TargetKind.PERSON,
            location=area("alpha", -1),
            identity_claim=identity(seconds=-1),
        )
        visitor = observation(
            "visitor-a",
            kind=TargetKind.PERSON,
            location=area("gamma", 0),
        )

        result = self.resolve(known, visitor)

        self.assertEqual((result.count_minimum, result.count_maximum), (2, 2))

    def test_adjacent_radar_after_face_keeps_visitor_uncertainty(self) -> None:
        person=observation(
            "visual-a",kind=TargetKind.PERSON,location=area("alpha",-8),identity_claim=identity(seconds=-8),
        )
        radar=observation(
            "radar-b",kind=TargetKind.UNKNOWN_LIVING,location=area("beta",0),
            dependency_group="radar-b",
        )
        result=self.resolve(person,radar)
        self.assertEqual((result.count_minimum,result.count_maximum),(1,2))
        self.assertIn("presence_count_is_an_interval",result.conflicts)

    def test_unstable_count_spike_remains_interval(self) -> None:
        device=observation(
            "device-a",kind=TargetKind.DEVICE,location=area("alpha",-20,quality=Quality.MEDIUM),
            identity_claim=identity(seconds=-20,method="registered_owner"),
        )
        spike=observation(
            "radar-a",kind=TargetKind.UNKNOWN_LIVING,location=area("alpha",0),
            count=CountClaim(1,2,at(0),False),active_since=-1,dependency_group="radar-a",
        )
        result=self.resolve(device,spike)
        self.assertEqual((result.count_minimum,result.count_maximum),(1,2))

    def test_same_area_stable_count_two_preserves_second_person(self) -> None:
        person=observation(
            "visual-a",kind=TargetKind.PERSON,location=area("alpha",-1),identity_claim=identity(seconds=-1),
        )
        count=observation(
            "count-a",kind=TargetKind.PERSON,location=area("alpha",0),
            count=CountClaim(2,2,at(0),True),dependency_group="camera-a",
        )
        result=self.resolve(person,count)
        self.assertEqual((result.count_minimum,result.count_maximum),(2,2))

    def test_transient_aggregate_two_is_provisional(self) -> None:
        count=observation(
            "count-a",kind=TargetKind.PERSON,location=area("alpha",0),
            count=CountClaim(2,2,at(0),False),active_since=-1,dependency_group="camera-a",
        )
        result=self.resolve(count)
        self.assertEqual((result.count_minimum,result.count_maximum),(1,2))

    def test_sustained_aggregate_two_becomes_exact(self) -> None:
        count=observation(
            "count-a",kind=TargetKind.PERSON,location=area("alpha",-5),
            count=CountClaim(2,2,at(-5),False),active_since=-5,dependency_group="camera-a",
        )
        result=self.resolve(count)
        self.assertEqual((result.count_minimum,result.count_maximum),(2,2))

    def test_event_and_aggregate_in_same_dependency_group_are_not_added(self) -> None:
        event=observation(
            "event-a",kind=TargetKind.PERSON,target_id=None,location=area("alpha",0),
            dependency_group="camera-target-a",
        )
        aggregate=observation(
            "count-a",kind=TargetKind.PERSON,location=area("alpha",0),
            count=CountClaim(1,1,at(0),True),dependency_group="camera-target-a",
        )
        result=self.resolve(event,aggregate)
        self.assertEqual((result.count_minimum,result.count_maximum),(1,1))

    def test_previous_direct_path_beats_newer_device_jump(self) -> None:
        prior_location=area("beta",-5)
        previous=PresenceSnapshot(
            contract_version=CONTRACT_VERSION,snapshot_id="previous",revision=6,evaluated_at=at(-5),
            presences=(PresenceHypothesis(
                hypothesis_id="person:person_a",kind=TargetKind.PERSON,identity="person_a",
                location=prior_location,location_status="resolved",certainty=Quality.HIGH,
                source_ids=("source.visual",),candidate_areas=("beta",),
            ),),devices=(),count_minimum=1,count_maximum=1,coverage_degraded=False,
        )
        device=observation(
            "device-a",kind=TargetKind.DEVICE,location=area("alpha",-10,quality=Quality.MEDIUM),
            identity_claim=identity(seconds=-10,method="registered_owner"),
        )
        path=observation("path-b",kind=TargetKind.PERSON,location=area("beta",-1))
        result=self.resolve(device,path,previous=previous)
        person=next(item for item in result.presences if item.identity == "person_a")
        self.assertEqual(person.location.area,"beta")
        self.assertEqual((result.count_minimum,result.count_maximum),(1,1))

    def test_same_animal_target_across_areas_is_one_trajectory(self) -> None:
        first=observation("animal-a1",kind=TargetKind.ANIMAL,target_id="animal-a",location=area("alpha",-4))
        second=observation("animal-a2",kind=TargetKind.ANIMAL,target_id="animal-a",location=area("beta",0))
        result=self.resolve(first,second)
        self.assertEqual((result.count_minimum,result.count_maximum),(1,1))
        self.assertEqual(result.presences[0].location.area,"beta")
        self.assertIsNone(result.presences[0].identity)

    def test_two_animal_aggregates_with_overlapping_coverage_remain_ambiguous(self) -> None:
        first=observation(
            "animal-count-a",kind=TargetKind.ANIMAL,location=area("alpha",-1),coverage_group="shared-view",
        )
        second=observation(
            "animal-count-b",kind=TargetKind.ANIMAL,location=area("beta",0),coverage_group="shared-view",
        )
        result=self.resolve(first,second)
        self.assertEqual((result.count_minimum,result.count_maximum),(1,2))
        self.assertTrue(all(item.identity is None for item in result.presences))

    def test_person_and_animal_are_never_merged(self) -> None:
        person=observation(
            "visual-a",kind=TargetKind.PERSON,location=area("alpha"),identity_claim=identity(),
        )
        animal=observation("animal-a",kind=TargetKind.ANIMAL,target_id="animal-a",location=area("alpha"))
        result=self.resolve(person,animal)
        self.assertEqual((result.count_minimum,result.count_maximum),(2,2))
        self.assertEqual({item.kind for item in result.presences},{TargetKind.PERSON,TargetKind.ANIMAL})

    def test_missing_source_degrades_coverage_without_asserting_empty(self) -> None:
        result=self.resolve(unavailable=("source.offline",))
        self.assertTrue(result.coverage_degraded)
        self.assertIn("coverage_degraded",result.reasons)

    def test_resolution_is_independent_of_input_order(self) -> None:
        observations = (
            observation(
                "device-a",
                kind=TargetKind.DEVICE,
                location=area("alpha", -8, quality=Quality.MEDIUM),
                identity_claim=identity(seconds=-8, method="registered_owner"),
            ),
            observation(
                "visual-a",
                kind=TargetKind.PERSON,
                location=area("beta", -2),
                identity_claim=identity(seconds=-2),
            ),
            observation(
                "animal-a",
                kind=TargetKind.ANIMAL,
                target_id="animal-a",
                location=area("gamma", -1),
            ),
        )

        results = [self.resolve(*items) for items in permutations(observations)]

        self.assertTrue(all(result == results[0] for result in results[1:]))


if __name__ == "__main__":
    unittest.main()
