from __future__ import annotations

import unittest
from dataclasses import replace

from presence_engine.engine import (
    EvidenceStore,
    IdentityClaim,
    ImageReference,
    Quality,
    RevisionDimension,
    RevisionStamp,
    TargetKind,
    resolve_detection,
)

from helpers import area, at, identity, observation


class DetectionTests(unittest.TestCase):
    def test_recognition_time_does_not_replace_detection_time(self) -> None:
        visual=observation("visual",event_id="event-a",detected=0,received=1,location=area("alpha",0))
        face=observation(
            "face",
            event_id="event-a",
            detected=0,
            received=45,
            identity_claim=identity(seconds=45),
            location=area("alpha",0),
        )
        result=resolve_detection("event-a",(visual,face),processed_at=at(46),revision=2)
        self.assertEqual(result.detected_at,at(0))
        self.assertEqual(result.recognized_at,at(45))
        self.assertEqual(result.spatial_observed_at,at(0))

    def test_late_current_zone_revises_same_event_without_retrodating(self) -> None:
        store=EvidenceStore()
        initial=observation(
            "event-a",
            event_id="event-a",
            detected=0,
            received=1,
            location=area("alpha",0),
            revisions={RevisionDimension.LOCATION:RevisionStamp(1,at(0))},
        )
        # Initial area represents only a broad/placeholder interpretation.
        initial=replace(initial,location=replace(initial.location,area="alpha",method="scope_fallback"))
        store.upsert(initial)
        late=replace(
            initial,
            received_at=at(12),
            location=area("beta",12,method="frigate_current_zone"),
            revisions={RevisionDimension.LOCATION:RevisionStamp(2,at(12))},
        )
        update=store.upsert(late)
        result=resolve_detection("event-a",store.by_event("event-a"),processed_at=at(13),revision=update.record_revision)
        self.assertEqual(result.detection_id,"event-a")
        self.assertEqual(result.revision,2)
        self.assertEqual(result.detected_at,at(0))
        self.assertEqual(result.location.area,"beta")
        self.assertEqual(result.spatial_observed_at,at(12))

    def test_detection_preserves_native_classification(self) -> None:
        dog = observation(
            "animal-a",
            event_id="event-animal",
            kind=TargetKind.ANIMAL,
            classification="dog",
            detected=3,
            received=4,
            location=area("alpha", 3),
        )

        result = resolve_detection(
            "event-animal",
            (dog,),
            processed_at=at(5),
            revision=1,
        )

        self.assertEqual(result.classification, "dog")
        self.assertEqual(result.kind, TargetKind.ANIMAL)

    def test_detection_exposes_event_image_identity_details_and_sources(self) -> None:
        visual = observation(
            "event-a",
            source_id="camera_events",
            event_id="event-a",
            detected=0,
            received=1,
            location=area("alpha", 0),
            image=ImageReference(
                reference="frigate:event:event-a",
                observed_at=at(1),
                area="alpha",
                event_id="event-a",
            ),
        )
        face = observation(
            "event-a:face",
            source_id="camera_faces",
            event_id="event-a",
            detected=8,
            received=8,
            identity_claim=IdentityClaim(
                "person_a",
                at(8),
                "frigate_face_recognition",
                Quality.HIGH,
                0.94,
            ),
        )

        result = resolve_detection(
            "event-a",
            (visual, face),
            processed_at=at(9),
            revision=2,
        )

        self.assertEqual(result.identity_method, "frigate_face_recognition")
        self.assertEqual(result.identity_score, 0.94)
        self.assertEqual(result.source_ids, ("camera_events", "camera_faces"))
        self.assertEqual(result.image, visual.image)


if __name__ == "__main__":
    unittest.main()
