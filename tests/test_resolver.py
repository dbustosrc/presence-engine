from __future__ import annotations

from dataclasses import replace

import unittest
from itertools import permutations

from presence_engine.engine import (
    CONTRACT_VERSION,
    CountClaim,
    FrozenClock,
    IdentityClaim,
    ObservationStatus,
    PresenceConfig,
    PresenceHypothesis,
    PresenceResolver,
    PresenceSnapshot,
    Quality,
    SourceRef,
    SpatialClaim,
    SpatialLevel,
    TargetKind,
)

from helpers import area, at, floor, identity, observation
from presence_engine.public_projection import _active_areas


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
        self.assertEqual(person.location.level,SpatialLevel.HOME)
        self.assertEqual(person.location_status,"device_person_separation_possible")

    def test_stale_device_does_not_hide_a_real_visitor(self) -> None:
        device=observation(
            "device-a",kind=TargetKind.DEVICE,location=area("alpha",-300,quality=Quality.MEDIUM),
            identity_claim=identity(seconds=-300,method="registered_owner"),
        )
        visitor=observation(
            "target-b",kind=TargetKind.PERSON,target_id="target-b",location=area("gamma",0),
        )
        result=self.resolve(device,visitor)
        self.assertEqual((result.count_minimum,result.count_maximum),(1,2))
        self.assertIn("presence_count_is_an_interval",result.conflicts)

    def test_floor_scope_identity_can_be_refined_by_current_area_evidence(self) -> None:
        person=observation(
            "visual-a",kind=TargetKind.PERSON,location=floor(-4),identity_claim=identity(seconds=-4),
        )
        area_evidence=observation(
            "target-a",kind=TargetKind.PERSON,target_id="target-a",location=area("alpha",0),
        )
        result=self.resolve(person,area_evidence)
        self.assertEqual((result.count_minimum,result.count_maximum),(1,2))
        named=next(p for p in result.presences if p.identity)
        self.assertEqual(named.location.area,"alpha")
        self.assertEqual(named.location.quality,Quality.MEDIUM)

    def test_anonymous_room_body_does_not_choose_between_compatible_people(self) -> None:
        first=observation("person-a",location=floor(-5),identity_claim=identity("person_a",-5))
        second=observation("person-b",location=floor(-1),identity_claim=identity("person_b",-1))
        body=observation("radar",family="binary_presence",kind=TargetKind.UNKNOWN_LIVING,
            location=area("beta",0),count=CountClaim(1,1,at(0),True))
        for ordered in permutations((first,second,body)):
            result=self.resolve(*ordered)
            known=[p for p in result.presences if p.identity]
            self.assertEqual({p.identity for p in known},{"person_a","person_b"})
            self.assertTrue(all(p.location.level is SpatialLevel.FLOOR for p in known))
            self.assertTrue(all("beta" in p.candidate_areas for p in known))
            anonymous,=[p for p in result.presences if p.identity is None]
            self.assertEqual((anonymous.location.area,anonymous.location_status),("beta","possible"))
            self.assertEqual((result.count_minimum,result.count_maximum),(2,3))
            self.assertIn("anonymous_body_has_multiple_identity_candidates",result.reasons)

    def test_old_floor_identity_is_not_a_current_room_association(self) -> None:
        old=observation("person-a",location=floor(-30),identity_claim=identity("person_a",-30))
        body=observation("radar",family="binary_presence",kind=TargetKind.UNKNOWN_LIVING,
            location=area("beta",0),count=CountClaim(1,1,at(0),True))
        result=self.resolve(old,body)
        person=next(p for p in result.presences if p.identity)
        self.assertEqual(person.location,floor(-30))
        self.assertTrue(any(p.identity is None and p.location.area=="beta" for p in result.presences))
        self.assertEqual((result.count_minimum,result.count_maximum),(1,2))

    def test_fresh_floor_identity_and_anonymous_radar_are_not_an_exact_room_identity(self) -> None:
        person=observation("face",location=floor(-1),identity_claim=identity("person_a",-1))
        radar=observation("radar",family="binary_presence",kind=TargetKind.UNKNOWN_LIVING,
            location=area("alpha",0),count=CountClaim(1,1,at(0),True))
        result=self.resolve(person,radar)
        named=next(p for p in result.presences if p.identity)
        self.assertEqual(named.location.area,"alpha")
        self.assertEqual(named.location_status,"ambiguous_movement")
        self.assertEqual(named.location.quality,Quality.MEDIUM)
        self.assertEqual(named.identity_source_ids,("source.face",))
        self.assertEqual((result.count_minimum,result.count_maximum),(1,2))

    def test_current_room_on_the_same_identified_visual_target_is_exact(self) -> None:
        person=observation("face",family="frigate_event",target_id="body-a",
            location=floor(-1),identity_claim=identity("person_a",-1))
        body=observation("body",family="frigate_event",target_id="body-a",location=area("alpha",0))
        items=tuple(replace(o,source=replace(o.source,native_id="camera")) for o in (person,body))
        for ordered in permutations(items):
            result=self.resolve(*ordered)
            named,=result.presences
            self.assertEqual(named.location,body.location)
            self.assertEqual(named.identity_source_ids,("source.face",))
            self.assertEqual((result.count_minimum,result.count_maximum),(1,1))

    def test_radar_fully_explained_by_a_dog_cannot_locate_a_floor_identity(self) -> None:
        person=observation("face",location=floor(-1),identity_claim=identity("person_a",-1))
        dog=observation("dog",family="frigate_event",kind=TargetKind.ANIMAL,classification="dog",
            target_id="dog-a",location=area("alpha",0),count=CountClaim(1,1,at(0),True))
        radar=observation("radar",family="binary_presence",kind=TargetKind.UNKNOWN_LIVING,
            location=area("alpha",0),count=CountClaim(1,1,at(0),True))
        for ordered in permutations((person,dog,radar)):
            result=self.resolve(*ordered)
            named=next(p for p in result.presences if p.identity)
            self.assertEqual(named.location,person.location)
            self.assertEqual((result.count_minimum,result.count_maximum),(2,3))

    def test_radar_fully_explained_by_a_dog_cannot_locate_a_device_owner(self) -> None:
        phone=observation("phone",family="bermuda_area",kind=TargetKind.DEVICE,
            location=area("alpha",-1,quality=Quality.MEDIUM),identity_claim=identity("person_a",-1,method="registered_owner"))
        dog=observation("dog",family="frigate_event",kind=TargetKind.ANIMAL,classification="dog",
            target_id="dog-a",location=area("alpha",0),count=CountClaim(1,1,at(0),True))
        radar=observation("radar",family="binary_presence",kind=TargetKind.UNKNOWN_LIVING,
            location=area("alpha",0),count=CountClaim(1,1,at(0),True))
        for ordered in permutations((phone,dog,radar)):
            result=self.resolve(*ordered)
            named=next(p for p in result.presences if p.identity)
            self.assertEqual(named.location.level,SpatialLevel.HOME)
            self.assertIsNone(named.location.area)
            self.assertTrue(any(p.kind is TargetKind.ANIMAL for p in result.presences))

    def test_distinct_visual_visitor_is_not_hidden_by_multiple_floor_identities(self) -> None:
        first=observation("person-a",family="frigate_event",target_id="body-a",
            location=floor(-5),identity_claim=identity("person_a",-5))
        second=observation("person-b",family="frigate_event",target_id="body-b",
            location=floor(-1),identity_claim=identity("person_b",-1))
        visitor=observation("visitor",family="frigate_event",target_id="visitor",
            location=area("beta",0))
        items=tuple(replace(o,source=replace(o.source,native_id="camera")) for o in (first,second,visitor))
        for ordered in permutations(items):
            result=self.resolve(*ordered)
            self.assertEqual((result.count_minimum,result.count_maximum),(3,3))
            known=[p for p in result.presences if p.identity]
            self.assertTrue(all(p.location.level is SpatialLevel.FLOOR for p in known))
            body,=[p for p in result.presences if p.identity is None]
            self.assertEqual(body.location.area,"beta")
            self.assertNotIn("anonymous_body_has_multiple_identity_candidates",result.reasons)

    def test_animal_overlap_does_not_block_an_additional_person_supported_by_radar(self) -> None:
        person=observation("face",location=floor(-1),identity_claim=identity("person_a",-1))
        phone=observation("phone",family="bermuda_area",kind=TargetKind.DEVICE,
            location=area("alpha",-1,quality=Quality.MEDIUM),identity_claim=identity("person_a",-1,method="registered_owner"))
        dog=observation("dog",family="frigate_event",kind=TargetKind.ANIMAL,classification="dog",
            target_id="dog-a",location=area("alpha",0),count=CountClaim(1,1,at(0),True))
        radar=observation("radar",family="binary_presence",kind=TargetKind.UNKNOWN_LIVING,
            location=area("alpha",0),count=CountClaim(2,2,at(0),True))
        for candidate in (person,phone):
            for ordered in permutations((candidate,dog,radar)):
                result=self.resolve(*ordered)
                named=next(p for p in result.presences if p.identity)
                self.assertEqual(named.location.area,"alpha" if candidate is person else None)
                self.assertTrue(any(p.kind is TargetKind.ANIMAL for p in result.presences))
                self.assertIn("anonymous_count_may_include_animal",result.reasons)

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

    def test_registered_device_and_same_area_body_retain_identity_uncertainty(self) -> None:
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

        self.assertEqual((result.count_minimum, result.count_maximum), (1, 2))
        person = next(item for item in result.presences if item.identity == "person_a")
        self.assertIsNone(person.location.area)
        self.assertEqual(person.location_status, "home_from_device")
        self.assertEqual(person.identity_quality, Quality.MEDIUM)
        self.assertEqual(result.devices[0].location.area, "alpha")

    def test_owned_static_radio_and_anonymous_body_do_not_prove_one_named_person(self) -> None:
        phone=observation("phone",family="bermuda_area",kind=TargetKind.DEVICE,
            location=area("alpha",-2,quality=Quality.MEDIUM),identity_claim=identity("person_a",-2,method="registered_owner"))
        body=observation("radar",family="binary_presence",kind=TargetKind.UNKNOWN_LIVING,
            location=area("alpha",0),count=CountClaim(1,1,at(0),True))
        for ordered in permutations((phone,body)):
            result=self.resolve(*ordered)
            named=next(p for p in result.presences if p.identity)
            self.assertNotIn(body.source.source_id,named.identity_source_ids)
            self.assertNotIn(body.source.source_id,named.location_source_ids)
            self.assertEqual(named.location.level,SpatialLevel.HOME)
            self.assertTrue(any(p.identity is None and p.location.area=="alpha" for p in result.presences))
            self.assertEqual((result.count_minimum,result.count_maximum),(1,2))

    def test_face_radio_and_radar_expose_spatial_support_without_rewriting_face_clock(self) -> None:
        face=observation("face",family="frigate_event",target_id="body-a",
            location=area("alpha",-2),identity_claim=identity("person_a",-3))
        phone=observation("phone",family="bermuda_area",kind=TargetKind.DEVICE,target_id="phone-a",
            location=area("alpha",-1,quality=Quality.MEDIUM),identity_claim=identity("person_a",-1,method="registered_owner"))
        radar=observation("radar",family="binary_presence",kind=TargetKind.UNKNOWN_LIVING,
            location=area("alpha",0),count=CountClaim(1,1,at(0),True))
        for ordered in permutations((face,phone,radar)):
            result=self.resolve(*ordered)
            person,=result.presences
            self.assertEqual(person.location_source_ids,("source.face","source.phone","source.radar"))
            self.assertEqual(person.identity_source_ids,("source.face",))
            self.assertEqual(person.location.observed_at,at(-2))
            self.assertEqual(person.identity_observed_at,at(-3))
            self.assertEqual(person.location.quality,Quality.HIGH)
            self.assertEqual((result.count_minimum,result.count_maximum),(1,1))
        self.assertEqual(face.location.observed_at,at(-2))

    def test_spatial_corroboration_rejects_old_conflicting_and_other_owner_radio(self) -> None:
        face=observation("face",family="frigate_event",target_id="body-a",
            location=area("alpha",0),identity_claim=identity("person_a",0))
        phone=observation("phone",family="bermuda_area",kind=TargetKind.DEVICE,target_id="phone-a",
            location=area("alpha",-1,quality=Quality.MEDIUM),identity_claim=identity("person_a",-1,method="registered_owner"))
        for other in (replace(phone,location=area("alpha",-30,quality=Quality.MEDIUM)),
                      replace(phone,location=area("delta",-1,quality=Quality.MEDIUM)),
                      replace(phone,identity=identity("person_b",-1,method="registered_owner")),
                      replace(phone,location=area("alpha",1,quality=Quality.MEDIUM)),
                      replace(phone,location=area("alpha",-1,quality=Quality.LOW))):
            with self.subTest(other=other):
                result=self.resolve(face,other)
                person=next(p for p in result.presences if p.identity=="person_a")
                self.assertEqual(person.location_source_ids,("source.face",))
        old_radar=observation("radar",family="binary_presence",kind=TargetKind.UNKNOWN_LIVING,
            location=area("alpha",-30),count=CountClaim(1,1,at(-30),True))
        for radar in (old_radar,replace(old_radar,location=area("alpha",0,quality=Quality.LOW)),
                      replace(old_radar,location=area("alpha",1))):
            result=self.resolve(face,radar)
            self.assertEqual(result.presences[0].location_source_ids,("source.face",))

    def test_radio_support_cannot_replace_primary_body_source_or_promote_ap_gps(self) -> None:
        face=observation("face",family="frigate_event",target_id="body-a",
            location=area("alpha",0),identity_claim=identity("person_a",0))
        phone=observation("aaa-phone",family="bermuda_area",kind=TargetKind.DEVICE,target_id="phone-a",
            location=area("alpha",-1,quality=Quality.MEDIUM),identity_claim=identity("person_a",-1,method="registered_owner"))
        result=self.resolve(face,phone)
        person,=result.presences
        self.assertEqual(person.location_source_ids,("source.face","source.aaa-phone"))
        from presence_engine.public_projection import identity_projection
        self.assertEqual(identity_projection(result,"person_a")["location_source"],"source.face")
        home=SpatialClaim(SpatialLevel.HOME,at(-1),method="wifi_connection",quality=Quality.LOW)
        wifi=replace(phone,source=SourceRef("source.wifi","wifi_tracker"),location=home,
            network_attachment="AP Alpha",network_attachment_area="alpha",network_attachment_observed_at=at(-1))
        gps=replace(phone,source=SourceRef("source.gps","gps_tracker"),location=replace(home,method="gps_device_home"))
        for device in (wifi,gps):
            result=self.resolve(face,device)
            person,=result.presences
            self.assertEqual(person.location_source_ids,("source.face",))
            self.assertIn(device.source.source_id,person.source_ids)
            self.assertEqual(person.location,face.location)
            self.assertEqual(person.identity_source_ids,("source.face",))
        result=self.resolve(face)
        self.assertEqual(result.presences[0].location_source_ids,("source.face",))

    def test_home_scope_and_registered_device_do_not_identify_a_room_body(self) -> None:
        home = observation(
            "person-home",
            kind=TargetKind.PERSON,
            location=SpatialClaim(
                level=SpatialLevel.HOME,
                method="home_scope",
                quality=Quality.LOW,
                observed_at=at(-20),
            ),
            identity_claim=identity(seconds=-20, method="home_scope"),
        )
        device = observation(
            "device-a",
            kind=TargetKind.DEVICE,
            target_id="device-a",
            location=area("alpha", -2, quality=Quality.MEDIUM),
            identity_claim=identity(seconds=-2, method="registered_owner"),
        )
        room = observation(
            "radar-a",
            kind=TargetKind.UNKNOWN_LIVING,
            location=area("alpha", 0),
            count=CountClaim(1, 1, at(0), True),
            dependency_group="radar-a",
        )

        result = self.resolve(home, device, room)

        self.assertEqual((result.count_minimum, result.count_maximum), (1, 2))
        person = next(item for item in result.presences if item.identity == "person_a")
        self.assertIsNone(person.location.area)
        self.assertEqual(person.location_status, "resolved")
        self.assertEqual(
            set(person.source_ids),
            {"source.person-home", "source.device-a"},
        )

    def test_phone_and_physical_presence_in_different_rooms_remain_separate(self) -> None:
        home = observation(
            "person-home",
            kind=TargetKind.PERSON,
            location=SpatialClaim(
                level=SpatialLevel.HOME,
                method="home_scope",
                quality=Quality.LOW,
                observed_at=at(-20),
            ),
            identity_claim=identity(seconds=-20, method="home_scope"),
        )
        phone = observation(
            "device-a",
            kind=TargetKind.DEVICE,
            target_id="device-a",
            location=area("alpha", -2, quality=Quality.MEDIUM),
            identity_claim=identity(seconds=-2, method="registered_owner"),
        )
        physical_presence = observation(
            "radar-delta",
            kind=TargetKind.UNKNOWN_LIVING,
            location=area("delta", 0),
            count=CountClaim(1, 1, at(0), True),
            dependency_group="radar-delta",
        )

        result = self.resolve(home, phone, physical_presence)

        self.assertEqual((result.count_minimum, result.count_maximum), (1, 2))
        self.assertIn("presence_count_is_an_interval", result.conflicts)
        self.assertIn("device_separated_from_physical_presence", result.reasons)
        person = next(item for item in result.presences if item.identity == "person_a")
        self.assertEqual(person.location.level, SpatialLevel.HOME)
        self.assertEqual(person.location_status, "device_person_separation_possible")
        self.assertEqual(person.candidate_areas, ())
        self.assertEqual(
            set(person.source_ids),
            {"source.person-home", "source.device-a"},
        )
        possible = next(item for item in result.presences if item.identity is None)
        self.assertEqual(possible.location.area, "delta")
        self.assertEqual(possible.location_status, "resolved")
        self.assertEqual(result.devices[0].location.area, "alpha")

    def test_registered_device_alone_supports_home_not_owner_room(self) -> None:
        device = observation(
            "device-a",
            kind=TargetKind.DEVICE,
            target_id="device-a",
            location=area("alpha", 0, quality=Quality.MEDIUM),
            identity_claim=identity(seconds=0, method="registered_owner"),
        )

        result = self.resolve(device)

        self.assertEqual((result.count_minimum, result.count_maximum), (1, 1))
        person = result.presences[0]
        self.assertEqual(person.location.level, SpatialLevel.HOME)
        self.assertIsNone(person.location.area)
        self.assertEqual(person.location_status, "home_from_device")
        self.assertEqual(result.devices[0].location.area, "alpha")

    def test_device_separation_does_not_lower_independent_physical_population(self) -> None:
        phone=observation("phone",family="bermuda_area",kind=TargetKind.DEVICE,
            location=area("alpha",-1,quality=Quality.MEDIUM),identity_claim=identity(method="registered_owner"))
        first=observation("radar-a",family="binary_presence",kind=TargetKind.UNKNOWN_LIVING,location=area("alpha"))
        second=observation("radar-b",family="binary_presence",kind=TargetKind.UNKNOWN_LIVING,location=area("delta"))
        for ordered in permutations((phone,first,second)):
            result=self.resolve(*ordered)
            self.assertEqual((result.count_minimum,result.count_maximum),(2,3))
            self.assertEqual({p.location.area for p in result.presences if p.identity is None},{"alpha","delta"})
            self.assertTrue(all(a.count.minimum==1 for a in result.area_occupancies))

    def test_multiple_registered_devices_are_alternative_support_for_one_person(self) -> None:
        first = observation(
            "device-a",
            kind=TargetKind.DEVICE,
            target_id="device-a",
            location=area("alpha", -2, quality=Quality.MEDIUM),
            identity_claim=identity(seconds=-2, method="registered_owner"),
        )
        second = observation(
            "device-b",
            kind=TargetKind.DEVICE,
            target_id="device-b",
            location=area("beta", 0, quality=Quality.MEDIUM),
            identity_claim=identity(seconds=0, method="registered_owner"),
        )

        result = self.resolve(first, second)

        self.assertEqual((result.count_minimum, result.count_maximum), (1, 1))
        self.assertEqual(len(result.presences), 1)
        self.assertEqual(result.presences[0].location.level, SpatialLevel.HOME)
        self.assertEqual({item.location.area for item in result.devices}, {"alpha", "beta"})

    def test_registered_device_does_not_override_direct_area_evidence(self) -> None:
        visual = observation(
            "visual-a",
            kind=TargetKind.PERSON,
            location=area("beta", -1, quality=Quality.HIGH),
            identity_claim=identity(seconds=-1),
        )
        device = observation(
            "device-a",
            kind=TargetKind.DEVICE,
            target_id="device-a",
            location=area("alpha", 0, quality=Quality.MEDIUM),
            identity_claim=identity(seconds=0, method="registered_owner"),
        )

        result = self.resolve(visual, device)

        person = next(item for item in result.presences if item.identity == "person_a")
        self.assertEqual(person.location.area, "beta")
        self.assertEqual(person.location_status, "resolved")

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
        self.assertEqual((result.count_minimum,result.count_maximum),(1,3))

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

    def test_tracked_event_and_independent_room_counter_are_one_population(self) -> None:
        event=observation(
            "event-a",kind=TargetKind.PERSON,target_id="event-a",location=area("alpha",0),
            dependency_group="camera-target-a",
        )
        aggregate=observation(
            "count-a",kind=TargetKind.UNKNOWN_LIVING,location=area("alpha",0),
            count=CountClaim(1,1,at(0),True),dependency_group="mtr-alpha",
        )

        result=self.resolve(event,aggregate)

        self.assertEqual((result.count_minimum,result.count_maximum),(1,1))

    def test_two_tracked_events_consume_room_count_two(self) -> None:
        first=observation(
            "event-a",kind=TargetKind.PERSON,target_id="event-a",location=area("alpha",0),
        )
        second=observation(
            "event-b",kind=TargetKind.PERSON,target_id="event-b",location=area("alpha",0),
        )
        aggregate=observation(
            "count-a",kind=TargetKind.UNKNOWN_LIVING,location=area("alpha",0),
            count=CountClaim(2,2,at(0),True),dependency_group="mtr-alpha",
        )

        result=self.resolve(first,second,aggregate)

        self.assertEqual((result.count_minimum,result.count_maximum),(2,2))

    def test_multiple_anonymous_room_sensors_do_not_create_exact_duplicates(self) -> None:
        radar=observation(
            "radar",kind=TargetKind.UNKNOWN_LIVING,location=area("alpha",0),
            dependency_group="radar-alpha",
        )
        camera=observation(
            "camera-count",kind=TargetKind.PERSON,location=area("alpha",0),
            dependency_group="camera-alpha",
        )

        result=self.resolve(radar,camera)

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
        self.assertEqual((result.count_minimum,result.count_maximum),(1,2))

    def test_new_physical_room_and_device_release_unobserved_previous_room(self) -> None:
        home = observation(
            "home", kind=TargetKind.PERSON,
            location=SpatialClaim(SpatialLevel.HOME, observed_at=at(-100), method="home_scope", quality=Quality.LOW),
            identity_claim=identity(seconds=-100),
        )
        previous = self.resolve(
            home,
            observation("device-old", kind=TargetKind.DEVICE, location=area("alpha", -1),
                        identity_claim=identity(seconds=-1, method="registered_owner")),
            observation("face-old", location=area("alpha", 0),identity_claim=identity()),
        )
        self.resolver = PresenceResolver(self.resolver._config, FrozenClock(at(20)))
        device = observation("device-new", kind=TargetKind.DEVICE, location=area("gamma", 19),
                             identity_claim=identity(seconds=19, method="registered_owner"))
        new_radar = observation("radar-new", kind=TargetKind.UNKNOWN_LIVING,
                                location=area("gamma", 20))

        moved = self.resolve(home, device, new_radar, previous=previous)
        person = next(item for item in moved.presences if item.identity == "person_a")
        self.assertEqual(person.location.area, "gamma")
        self.assertEqual(person.location_status, "ambiguous_movement")
        self.assertEqual(person.location.quality,Quality.MEDIUM)
        self.assertEqual((moved.count_minimum, moved.count_maximum), (1, 2))

        still_observed = self.resolve(
            home, device, new_radar,
            observation("radar-old-active", kind=TargetKind.UNKNOWN_LIVING,
                        location=area("alpha", 20)),
            previous=previous,
        )
        person = next(item for item in still_observed.presences if item.identity == "person_a")
        self.assertEqual(person.location.area, "alpha")
        self.assertTrue(any(item.identity is None and item.location.area == "gamma"
                            for item in still_observed.presences))

        stale_device = observation(
            "device-left-behind", kind=TargetKind.DEVICE, location=area("gamma", -60),
            identity_claim=identity(seconds=-60, method="registered_owner"),
        )
        visitor = self.resolve(home, stale_device, new_radar, previous=previous)
        person = next(item for item in visitor.presences if item.identity == "person_a")
        self.assertEqual(person.location.area, "alpha")
        self.assertTrue(any(item.identity is None and item.location.area == "gamma"
                            for item in visitor.presences))

    def test_current_same_area_body_does_not_refresh_continued_identity(self) -> None:
        device = observation(
            "device", kind=TargetKind.DEVICE, location=area("alpha", -10),
            identity_claim=identity(seconds=-10, method="registered_owner"),
        )
        prior = self.resolve(device, observation("prior", location=area("alpha", -1),identity_claim=identity(seconds=-1)))
        for kind in (TargetKind.PERSON, TargetKind.UNKNOWN_LIVING):
            with self.subTest(kind=kind):
                current = observation("current", kind=kind, location=area("alpha", 0))
                result = self.resolve(device, current, previous=prior)
                person = next(p for p in result.presences if p.identity)
                self.assertEqual(person.location_status, "continued")
                self.assertEqual(person.location.observed_at, at(-1))
                self.assertEqual(person.location_source_ids, prior.presences[0].location_source_ids)
                self.assertEqual(person.identity_quality,Quality.MEDIUM)
                self.assertEqual(person.identity_method,"registered_device_presence")
                self.assertEqual(person.identity_observed_at,at(-10))
                self.assertEqual((result.count_minimum, result.count_maximum), (1, 2))
                self.assertEqual(result.area_occupancies[0].count.minimum,1)
                repeated = self.resolve(device, current, previous=result)
                known=next(p for p in repeated.presences if p.identity)
                self.assertEqual(known.location_status, "continued")
                self.assertEqual(known.location.observed_at, at(-1))

    def test_same_area_uncertain_or_older_evidence_does_not_refresh_continuity(self) -> None:
        device = observation(
            "device", kind=TargetKind.DEVICE, location=area("alpha", -10),
            identity_claim=identity(seconds=-10, method="registered_owner"),
        )
        prior = self.resolve(device, observation("prior", location=area("alpha", -1),identity_claim=identity(seconds=-1)))
        cases = (
            (),
            (observation("older", location=area("alpha", -2)),),
            (observation("possible", location=area("alpha", 0),
                         count=CountClaim(0, 1, at(0), True)),),
            (observation("radar", kind=TargetKind.UNKNOWN_LIVING, location=area("alpha", 0)),
             observation("animal", kind=TargetKind.ANIMAL, location=area("alpha", 0))),
        )
        for items in cases:
            with self.subTest(items=tuple(item.observation_id for item in items)):
                result = self.resolve(device, *items, previous=prior)
                person = next(item for item in result.presences if item.identity)
                self.assertEqual(person.location_status, "continued")
                self.assertEqual(person.location.observed_at, at(-1))
                if len(items) < 2:
                    self.assertEqual(_active_areas(result.presences)[0]["current_minimum_count"], 0)

    def test_one_current_target_does_not_refresh_two_continued_identities(self) -> None:
        devices = tuple(observation(
            name, kind=TargetKind.DEVICE, location=area("alpha", -10),
            identity_claim=identity(name, -10, method="registered_owner"),
        ) for name in ("person_a", "person_b"))
        prior = self.resolve(*(observation(
            "prior-" + name, location=area("alpha", -1), identity_claim=identity(name, -1),
        ) for name in ("person_a", "person_b")))
        for minimum in (1,2):
            with self.subTest(minimum=minimum):
                current = observation("population", location=area("alpha", 0),
                                      count=CountClaim(minimum, minimum, at(0), True))
                result = self.resolve(*devices, current, previous=prior)
                known=[p for p in result.presences if p.identity]
                self.assertEqual(len(known),2)
                self.assertTrue(all(item.location_status == "continued" for item in known))
                self.assertTrue(all(item.location.observed_at==at(-1) for item in known))
                self.assertTrue(any(p.identity is None for p in result.presences))
                self.assertEqual(result.count_maximum,2+minimum)

    def test_current_same_area_refresh_does_not_replace_direct_identity_evidence(self) -> None:
        face = observation("face", location=area("alpha", -1), identity_claim=identity(seconds=-1))
        result = self.resolve(face, observation("radar", kind=TargetKind.UNKNOWN_LIVING,
                                               location=area("alpha", 0)))
        person = result.presences[0]
        self.assertEqual(person.location_status, "resolved")
        self.assertEqual(person.location.observed_at, at(-1))
        self.assertEqual(person.identity_method, "face")

    def test_radio_gap_retains_supported_room_without_rolling_deadline(self) -> None:
        home = observation("home", family="person_home",
            location=SpatialClaim(SpatialLevel.HOME, at(-200), method="home_scope", quality=Quality.LOW),
            identity_claim=IdentityClaim("person_a", at(-200), "home_scope", Quality.MEDIUM))
        phone = observation("phone", family="bermuda_area", kind=TargetKind.DEVICE,
            location=area("beta", 0, quality=Quality.MEDIUM), identity_claim=identity(method="registered_owner"))
        def body(seconds):
            return observation("body", family="resolved_event", target_id="body-track",
                coverage_group="camera:beta", location=area("beta", seconds),
                count=CountClaim(1, 1, at(seconds), True))
        previous = self.resolve(home, phone, replace(body(0),identity=identity()))
        original = next(p for p in previous.presences if p.identity)
        for seconds in (15, 30, 89, 90):
            with self.subTest(seconds=seconds):
                self.resolver = PresenceResolver(self.resolver._config, FrozenClock(at(seconds)))
                result = self.resolve(home, body(seconds), previous=previous)
                person = next(p for p in result.presences if p.identity)
                self.assertEqual(person.location.area, "beta" if seconds < 90 else None)
                if seconds < 90:
                    self.assertEqual(person.location_status, "continued")
                    self.assertEqual(person.location.observed_at, original.location.observed_at)
                self.assertEqual(person.identity_observed_at, home.identity.observed_at)
                self.assertEqual((result.count_minimum, result.count_maximum), (1, 2))
                previous = result

    def test_radio_gap_needs_original_positive_support_and_does_not_hide_visitors(self) -> None:
        home = observation("home", family="person_home",
            location=SpatialClaim(SpatialLevel.HOME, at(-200), method="home_scope", quality=Quality.LOW),
            identity_claim=IdentityClaim("person_a", at(-200), "home_scope", Quality.MEDIUM))
        phone = observation("phone", family="bermuda_area", kind=TargetKind.DEVICE,
            location=area("beta", 0), identity_claim=identity(method="registered_owner"))
        original = observation("body", family="resolved_event", target_id="body-track",
            coverage_group="camera:beta", location=area("beta", 0), count=CountClaim(1, 1, at(0), True))
        prior = self.resolve(home, phone, original)
        self.resolver = PresenceResolver(self.resolver._config, FrozenClock(at(15)))
        cases = (
            (),
            (observation("other", location=area("beta", 15)),),
            (observation("body", kind=TargetKind.ANIMAL, location=area("beta", 15)),),
            (observation("body", location=area("beta", 15), count=CountClaim(0, 1, at(15), True)),),
            (observation("body", location=area("beta", 16)),),
            (observation("body", location=area("beta", 15), count=CountClaim(1, 1, at(16), True)),),
            (observation("body", location=area("beta", 15, quality=Quality.LOW)),),
            (observation("body", location=area("beta", 15), identity_claim=identity("visitor", 15)),),
        )
        for items in cases:
            with self.subTest(items=items):
                result = self.resolve(home, *items, previous=prior)
                owner = next(p for p in result.presences if p.identity == "person_a")
                self.assertIsNone(owner.location.area)
                if items and items[0].identity:
                    self.assertTrue(any(p.identity == "visitor" for p in result.presences))
        fresh_start = self.resolve(home, original)
        self.assertIsNone(next(p for p in fresh_start.presences if p.identity).location.area)
        unavailable = self.resolve(home, original, previous=prior, unavailable=("source.body",))
        self.assertIsNone(next(p for p in unavailable.presences if p.identity).location.area)

    def test_previous_snapshot_without_current_evidence_does_not_create_presence(self) -> None:
        previous=PresenceSnapshot(
            contract_version=CONTRACT_VERSION,snapshot_id="previous",revision=6,evaluated_at=at(-1),
            presences=(PresenceHypothesis(
                hypothesis_id="person:person_a",kind=TargetKind.PERSON,identity="person_a",
                location=area("alpha",-1),location_status="resolved",certainty=Quality.HIGH,
                source_ids=("source.visual",),candidate_areas=("alpha",),
            ),),devices=(),count_minimum=1,count_maximum=1,coverage_degraded=False,
        )

        result=self.resolve(previous=previous)

        self.assertEqual((result.count_minimum,result.count_maximum),(0,0))
        self.assertEqual(result.presences,())

    def test_same_animal_target_across_areas_is_one_trajectory(self) -> None:
        first=observation(
            "animal-a1",kind=TargetKind.ANIMAL,classification="dog",
            target_id="animal-a",location=area("alpha",-4),
        )
        second=observation(
            "animal-a2",kind=TargetKind.ANIMAL,classification="dog",
            target_id="animal-a",location=area("beta",0),
        )
        result=self.resolve(first,second)
        self.assertEqual((result.count_minimum,result.count_maximum),(1,1))
        self.assertEqual(result.presences[0].location.area,"beta")
        self.assertIsNone(result.presences[0].identity)
        self.assertEqual(result.presences[0].classification,"dog")

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

    def test_different_animal_classifications_are_not_deduplicated(self) -> None:
        dog = observation(
            "dog-count", kind=TargetKind.ANIMAL, classification="dog",
            location=area("alpha", -1), coverage_group="shared-view",
        )
        cat = observation(
            "cat-count", kind=TargetKind.ANIMAL, classification="cat",
            location=area("alpha", 0), coverage_group="shared-view",
        )

        result = self.resolve(dog, cat)

        self.assertEqual((result.count_minimum, result.count_maximum), (2, 2))
        self.assertEqual(
            {item.classification for item in result.presences},
            {"dog", "cat"},
        )

    def test_person_and_animal_are_never_merged(self) -> None:
        person=observation(
            "visual-a",kind=TargetKind.PERSON,location=area("alpha"),identity_claim=identity(),
        )
        animal=observation("animal-a",kind=TargetKind.ANIMAL,target_id="animal-a",location=area("alpha"))
        result=self.resolve(person,animal)
        self.assertEqual((result.count_minimum,result.count_maximum),(2,2))
        self.assertEqual({item.kind for item in result.presences},{TargetKind.PERSON,TargetKind.ANIMAL})

    def test_anonymous_radar_may_be_the_visual_animal(self) -> None:
        person=observation(
            "known",kind=TargetKind.PERSON,location=area("delta"),identity_claim=identity(),
        )
        dog=observation(
            "dog",kind=TargetKind.ANIMAL,classification="dog",target_id="dog-1",
            location=area("alpha"),
        )
        radar=observation(
            "radar",kind=TargetKind.UNKNOWN_LIVING,location=area("alpha"),
            count=CountClaim(1,1,at(0),True),dependency_group="radar-alpha",
        )

        result=self.resolve(person,dog,radar)

        self.assertEqual((result.count_minimum,result.count_maximum),(2,3))
        self.assertEqual(next(p for p in result.presences if p.kind is TargetKind.ANIMAL).classification,"dog")
        self.assertEqual(next(p for p in result.presences if p.kind is TargetKind.UNKNOWN_LIVING).location_status,"possible")

    def test_floor_radar_can_overlap_person_without_moving_person(self) -> None:
        person=observation(
            "known",kind=TargetKind.PERSON,location=area("alpha"),identity_claim=identity(),
        )
        radar=observation(
            "radar",kind=TargetKind.UNKNOWN_LIVING,
            location=SpatialClaim(
                level=SpatialLevel.FLOOR,floor="floor_alpha",candidates=(),
                method="ambiguous_zone",quality=Quality.MEDIUM,observed_at=at(0),
            ),
            count=CountClaim(1,1,at(0),True),dependency_group="radar-floor",
        )

        result=self.resolve(person,radar)

        self.assertEqual((result.count_minimum,result.count_maximum),(1,2))
        self.assertEqual(next(p for p in result.presences if p.identity).location.area,"alpha")

    def test_two_floor_radars_do_not_prove_two_visitors_near_one_person(self) -> None:
        person=observation(
            "known",kind=TargetKind.PERSON,location=area("alpha"),identity_claim=identity(),
        )
        radars=(
            observation(
                name,kind=TargetKind.UNKNOWN_LIVING,
                location=SpatialClaim(
                    level=SpatialLevel.FLOOR,floor="floor_alpha",candidates=(),
                    method="ambiguous_zone",quality=Quality.MEDIUM,observed_at=at(0),
                ),
                count=CountClaim(1,1,at(0),True),dependency_group=name,
            )
            for name in ("radar-one","radar-two")
        )

        result=self.resolve(person,*radars)

        self.assertEqual((result.count_minimum,result.count_maximum),(1,3))

    def test_floor_animal_and_floor_radar_may_describe_one_animal(self) -> None:
        dog=observation(
            "dog",kind=TargetKind.ANIMAL,classification="dog",target_id="dog-1",
            location=floor(0),
        )
        radar=observation(
            "radar",kind=TargetKind.UNKNOWN_LIVING,
            location=SpatialClaim(
                level=SpatialLevel.FLOOR,floor="floor_alpha",candidates=(),
                method="ambiguous_zone",quality=Quality.MEDIUM,observed_at=at(0),
            ),
            count=CountClaim(1,1,at(0),True),dependency_group="radar-floor",
        )

        result=self.resolve(dog,radar)

        self.assertEqual((result.count_minimum,result.count_maximum),(1,2))

    def test_anonymous_radar_on_another_floor_is_not_the_visual_animal(self) -> None:
        dog=observation(
            "dog",kind=TargetKind.ANIMAL,classification="dog",target_id="dog-1",
            location=area("alpha"),
        )
        radar=observation(
            "radar",kind=TargetKind.UNKNOWN_LIVING,location=area("delta"),
            count=CountClaim(1,1,at(0),True),dependency_group="radar-delta",
        )

        result=self.resolve(dog,radar)

        self.assertEqual((result.count_minimum,result.count_maximum),(2,2))

    def test_missing_source_degrades_coverage_without_asserting_empty(self) -> None:
        result=self.resolve(unavailable=("source.offline",))
        self.assertTrue(result.coverage_degraded)
        self.assertIn("coverage_degraded",result.reasons)
        self.assertEqual(result.unavailable_source_ids,("source.offline",))

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


class HeldAggregateScopeTests(unittest.TestCase):
    def test_held_floor_and_contained_room_are_not_independent_by_clock_age(self):
        from itertools import permutations
        room = observation("room", family="mtr_count", kind=TargetKind.UNKNOWN_LIVING,
            location=area("alpha", -40), count=CountClaim(1, 1, at(-40), True))
        scoped = observation("scope", family="mtr_count", kind=TargetKind.UNKNOWN_LIVING,
            location=floor(), count=CountClaim(1, 1, at(), True))
        owner = observation("owner", location=area("delta"), identity_claim=identity())
        resolver = PresenceResolver(PresenceConfig(), FrozenClock(at()))
        for ordered in permutations((room, scoped, owner)):
            result = resolver.resolve(ordered, revision=1)
            self.assertEqual((result.count_minimum, result.count_maximum), (2, 3))
            self.assertIn("cross_area_population_overlap", result.reasons)
            self.assertEqual(next(p for p in result.presences if p.identity).location.area, "delta")
            self.assertTrue(any(p.location == room.location for p in result.presences))
            self.assertTrue(any(p.location == scoped.location for p in result.presences))
        for count in (1, 2, 4):
            varied = replace(scoped, count=CountClaim(count, count, at(), True))
            result = resolver.resolve((room, varied), revision=1)
            self.assertEqual((result.count_minimum, result.count_maximum), (count, count + 1))
        ended = replace(scoped, status=ObservationStatus.ENDED, ended_at=at())
        self.assertEqual(resolver.resolve((room, ended), revision=1).count_maximum, 1)

    def test_held_aggregates_need_compatible_scope_not_only_shared_floor(self):
        room = observation("room", family="mtr_count", kind=TargetKind.UNKNOWN_LIVING,
            location=area("alpha", -40), count=CountClaim(1, 1, at(-40), True))
        scoped = observation("scope", family="mtr_count", kind=TargetKind.UNKNOWN_LIVING,
            location=floor(), count=CountClaim(1, 1, at(), True))
        resolver = PresenceResolver(PresenceConfig(adjacency={"alpha": frozenset({"beta"})}), FrozenClock(at()))
        for other in (replace(scoped, location=replace(scoped.location, candidates=("beta",))),
                      replace(scoped, location=replace(scoped.location, floor="other_floor")),
                      replace(scoped, location=area("beta"))):
            result = resolver.resolve((room, other), revision=1)
            self.assertEqual((result.count_minimum, result.count_maximum), (2, 2))


if __name__ == "__main__":
    unittest.main()
