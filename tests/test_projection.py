from __future__ import annotations

import unittest

from presence_engine.engine import (
    DetectionResult,
    ImageReference,
    Quality,
    TargetKind,
)
from presence_engine.projection import detection_payload

from helpers import area, at


class DetectionProjectionTests(unittest.TestCase):
    def test_detection_payload_is_self_contained_for_consumers(self) -> None:
        result = DetectionResult(
            contract_version=1,
            detection_id="event/a b",
            revision=3,
            status="resolved",
            kind=TargetKind.PERSON,
            identity="person_a",
            identity_quality=Quality.HIGH,
            location=area("alpha", 2),
            detected_at=at(0),
            recognized_at=at(7),
            spatial_observed_at=at(2),
            processed_at=at(8),
            evidence_ids=("event/a b", "event/a b:face"),
            classification="person",
            identity_method="frigate_face_recognition",
            identity_score=0.91,
            source_ids=("camera_events", "camera_faces"),
            image=ImageReference(
                reference="frigate:event:event/a b",
                observed_at=at(2),
                area="alpha",
                event_id="event/a b",
            ),
        )

        payload = detection_payload(result)

        self.assertEqual(payload["identity_score"], 0.91)
        self.assertEqual(payload["identity_method"], "frigate_face_recognition")
        self.assertEqual(payload["source_ids"], ["camera_events", "camera_faces"])
        self.assertEqual(
            payload["image"]["url"],
            "/api/frigate/notifications/event%2Fa%20b/snapshot.jpg",
        )
        self.assertEqual(payload["detected_at"], at(0).isoformat())
        self.assertEqual(payload["recognized_at"], at(7).isoformat())


if __name__ == "__main__":
    unittest.main()
