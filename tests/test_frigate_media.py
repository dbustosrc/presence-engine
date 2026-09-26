from __future__ import annotations

import unittest
from dataclasses import replace

from presence_engine.adapters import AdapterEnvelope
from presence_engine.codec import decode_observation, encode_observation
from presence_engine.projection import detection_payload
from presence_engine.public_projection import identity_projection
from presence_engine.runtime import PresenceRuntime

from helpers import at
from integration_helpers import integration_config


class FrigateMediaTests(unittest.TestCase):
    def setUp(self) -> None:
        self.runtime = PresenceRuntime(integration_config(), now=lambda: at(10))

    def event(self, second=1, *, event_id="event-a", ended=False, **facts):
        return AdapterEnvelope(
            "mqtt", "frigate/events",
            {"type": "end" if ended else "update", "after": {
                "id": event_id, "camera": "camera_a", "label": "person",
                "start_time": at(0).timestamp(), "frame_time": at(1).timestamp(),
                "end_time": at(second).timestamp() if ended else None,
                "current_zones": ["zone_alpha"], **facts,
            }},
            at(second), at(second),
        )

    def face(self, event_id="event-a", second=2):
        return AdapterEnvelope(
            "mqtt", "frigate/tracked_object_update",
            {"type": "face", "id": event_id, "camera": "camera_a",
             "name": "person_a", "score": 0.92, "timestamp": at(second).timestamp()},
            at(second), at(second),
        )

    def test_positive_without_movement_or_retained_media_still_executes_lifecycle(self):
        facts = dict(has_snapshot=False, has_clip=False, position_changes=0, false_positive=False)
        update = self.runtime.process(self.event(**facts))
        payload = detection_payload(update.detections[0])
        self.assertEqual(update.snapshot.count_minimum, 1)
        self.assertEqual(payload["kind"], "person")
        self.assertEqual(payload["source_diagnostics"]["frigate_events"], facts)
        self.assertEqual(payload["image"]["snapshot_status"], "temporary")
        self.assertIsNotNone(payload["image"]["url"])
        self.assertIsNone(payload["image"]["clip_url"])

        ended = self.runtime.process(self.event(3, ended=True, **facts))
        payload = detection_payload(ended.detections[0])
        self.assertEqual(ended.snapshot.count_maximum, 0)
        self.assertEqual(payload["status"], "ended_unidentified")
        self.assertEqual(payload["detected_at"], at(0).isoformat())
        self.assertEqual(payload["image"]["snapshot_status"], "unavailable")
        self.assertIsNone(payload["image"]["url"])
        self.assertIsNone(payload["image"]["clip_url"])
        self.assertIn("reference", payload["image"])
        self.assertEqual(self.runtime.latest_images, {})

        # Same native end time and same facts: no second publication.
        duplicate = self.runtime.process(replace(self.event(3, ended=True, **facts), received_at=at(4), observed_at=at(4)))
        self.assertFalse(duplicate.changed)
        self.assertEqual(duplicate.detections, ())

    def test_same_frame_media_updates_and_late_face_preserve_final_facts(self):
        self.runtime.process(self.event(has_snapshot=False, has_clip=False, position_changes=0))
        update = self.runtime.process(self.event(2, has_snapshot=True, has_clip=True, position_changes=1))
        self.assertEqual(update.detections[0].source_diagnostics["frigate_events"]["position_changes"], 1)
        self.runtime.process(self.face(second=3))
        ended = self.runtime.process(self.event(4, ended=True, has_snapshot=True, has_clip=True, position_changes=1))
        payload = detection_payload(ended.detections[0])
        self.assertEqual(payload["image"]["snapshot_status"], "retained")
        self.assertEqual(payload["image"]["clip_status"], "retained")
        self.assertIsNotNone(payload["image"]["url"])
        self.assertIsNotNone(payload["image"]["clip_url"])
        self.assertEqual(self.runtime.latest_images["person_a"].image.snapshot_status, "retained")
        identity = identity_projection(self.runtime.snapshot, "person_a", self.runtime.latest_images)
        self.assertEqual(identity["last_image"]["snapshot_status"], "retained")

        # An older frame arriving after the end cannot restore a transient URL.
        self.runtime.process(self.event(5, has_snapshot=False, has_clip=False))
        restored = PresenceRuntime(integration_config(), now=lambda: at(10))
        restored.restore_state(self.runtime.export_state())
        payload = detection_payload(restored.detection("event-a"))
        self.assertEqual(payload["source_diagnostics"]["frigate_events"]["has_snapshot"], True)
        self.assertEqual(payload["image"]["snapshot_status"], "retained")

    def test_temporary_failed_event_does_not_replace_previous_identity_photo(self):
        self.runtime.process(self.event(has_snapshot=True, has_clip=True))
        self.runtime.process(self.face())
        self.runtime.process(self.event(3, ended=True, has_snapshot=True, has_clip=True))
        previous = self.runtime.latest_images["person_a"]
        self.runtime.process(self.event(4, event_id="event-b", has_snapshot=False, has_clip=False))
        self.runtime.process(self.face("event-b", second=5))
        self.runtime.process(self.event(6, event_id="event-b", ended=True, has_snapshot=False, has_clip=False))
        self.assertEqual(self.runtime.latest_images["person_a"], previous)

    def test_missing_or_malformed_optional_facts_do_not_reject_detection(self):
        update = self.runtime.process(self.event(has_snapshot="false", has_clip=0, position_changes=True))
        self.assertEqual(update.snapshot.count_minimum, 1)
        self.assertEqual(update.detections[0].source_diagnostics, {})
        self.assertEqual(detection_payload(update.detections[0])["image"]["clip_status"], "unknown")
        saved = self.runtime.export_state()["observations"][0]
        for key in ("snapshot_status", "clip_status"):
            saved["image"].pop(key)
        saved.pop("source_diagnostics")
        old = decode_observation(saved)
        self.assertEqual(old.image.snapshot_status, "unknown")
        self.assertEqual(decode_observation(encode_observation(old)), old)

    def test_snapshot_and_clip_retention_are_independent(self):
        self.runtime.process(self.event(has_snapshot=True, has_clip=False))
        update = self.runtime.process(self.event(3, ended=True, has_snapshot=True, has_clip=False))
        payload = detection_payload(update.detections[0])
        self.assertIsNotNone(payload["image"]["url"])
        self.assertIsNone(payload["image"]["clip_url"])
        self.assertEqual(payload["image"]["clip_status"], "unavailable")


if __name__ == "__main__":
    unittest.main()
