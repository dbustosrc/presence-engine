from __future__ import annotations

import unittest

from presence_engine.engine import (
    ImageReference,
    PresenceHypothesis,
    PresenceSnapshot,
    Quality,
    TargetKind,
)
from presence_engine.public_projection import (
    identity_projection,
    public_presence_projection,
)
from presence_engine.runtime import ImageRecord

from helpers import area, at


class PublicProjectionTests(unittest.TestCase):
    def setUp(self) -> None:
        self.person = PresenceHypothesis(
            hypothesis_id="person:person_a",
            kind=TargetKind.PERSON,
            identity="person_a",
            location=area("alpha", 10, quality=Quality.MEDIUM, method="nearest_receiver"),
            location_status="resolved",
            certainty=Quality.HIGH,
            source_ids=("person_home", "device_area"),
            candidate_areas=("alpha",),
            classification="person",
            identity_quality=Quality.HIGH,
            identity_method="registered_device_owner",
            identity_observed_at=at(9),
            identity_score=0.95,
            identity_source_ids=("device_area",),
            location_source_ids=("device_area",),
        )
        self.dog = PresenceHypothesis(
            hypothesis_id="target:animal_a:1",
            kind=TargetKind.ANIMAL,
            identity=None,
            location=area("beta", 11, quality=Quality.HIGH, method="frigate_current_zone"),
            location_status="resolved",
            certainty=Quality.MEDIUM,
            source_ids=("frigate_events",),
            candidate_areas=("beta",),
            classification="dog",
            location_source_ids=("frigate_events",),
        )
        self.snapshot = PresenceSnapshot(
            contract_version=1,
            snapshot_id="snapshot-7",
            revision=7,
            evaluated_at=at(12),
            presences=(self.person, self.dog),
            devices=(),
            count_minimum=2,
            count_maximum=2,
            coverage_degraded=True,
            unavailable_source_ids=("source.offline",),
        )
        self.images = {
            "person_a": ImageRecord(
                identity="person_a",
                image=ImageReference(
                    reference="/api/example/image.jpg",
                    observed_at=at(8),
                    area="gamma",
                    event_id="event-a",
                ),
                detection_id="event-a",
            )
        }

    def test_public_projection_keeps_counts_species_and_revision_coherent(self) -> None:
        result = public_presence_projection(self.snapshot, self.images)

        self.assertEqual(result["state"], "on")
        self.assertEqual(result["revision"], 7)
        self.assertEqual(result["summary"]["persons"], 1)
        self.assertEqual(result["summary"]["dogs"], 1)
        self.assertEqual(result["summary"]["cats"], 0)
        self.assertEqual(
            {item["area"] for item in result["active_areas"]},
            {"alpha", "beta"},
        )
        self.assertEqual(result["unavailable_sources"], ["source.offline"])

    def test_identity_projection_separates_identity_location_and_image(self) -> None:
        result = identity_projection(self.snapshot, "person_a", self.images)

        self.assertEqual(result["state"], "alpha")
        self.assertEqual(result["confidence"], "high")
        self.assertEqual(result["location_source"], "device_area")
        self.assertEqual(result["location_confidence"], "medium")
        self.assertEqual(result["identity_confidence"], "high")
        self.assertEqual(result["identity_source"], "registered_device_owner")
        self.assertEqual(result["entity_picture"], "/api/example/image.jpg")
        self.assertEqual(result["last_image"]["area"], "gamma")

    def test_missing_identity_is_unknown_not_away_and_keeps_image_metadata(self) -> None:
        result = identity_projection(self.snapshot, "person_b", {})

        self.assertIsNone(result["state"])
        self.assertEqual(result["confidence"], "unknown")
        self.assertEqual(result["location_status"], "unknown")
        self.assertNotEqual(result["state"], "not_home")

    def test_area_presence_exposes_its_floor_as_scope(self) -> None:
        result = public_presence_projection(self.snapshot, self.images)

        person = next(item for item in result["presences"] if item["identity"])
        self.assertEqual(person["area"], "alpha")
        self.assertEqual(person["scope"], "floor_alpha")


if __name__ == "__main__":
    unittest.main()
