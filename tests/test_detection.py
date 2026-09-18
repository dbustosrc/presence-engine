from __future__ import annotations

import unittest
from dataclasses import replace

from presence_engine.engine import EvidenceStore, RevisionDimension, RevisionStamp, resolve_detection

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


if __name__ == "__main__":
    unittest.main()
