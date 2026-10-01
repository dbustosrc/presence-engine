from __future__ import annotations

from copy import deepcopy
import json
from pathlib import Path
import unittest
from datetime import datetime, timedelta

from presence_engine.adapters import AdapterEnvelope
from presence_engine.configuration import parse_configuration
from presence_engine.runtime import PresenceRuntime

from helpers import at


FIXTURE_DIRECTORY = Path(__file__).with_name("fixtures")


class ReplayFixtureTests(unittest.TestCase):
    def test_sanitized_scenarios_replay_deterministically(self) -> None:
        paths = sorted(FIXTURE_DIRECTORY.glob("*.json"))
        self.assertTrue(paths)
        for path in paths:
            with self.subTest(fixture=path.name):
                self._replay(path)

    def _replay(self, path: Path) -> None:
        fixture = json.loads(path.read_text(encoding="utf-8"))
        start = datetime.fromisoformat(fixture["start_at"]) if fixture.get("start_at") else at(0)
        instant = lambda seconds: start + timedelta(seconds=seconds)
        current = [instant(0)]
        runtime = PresenceRuntime(
            parse_configuration(fixture["configuration"]),
            now=lambda: current[0],
        )

        for step in fixture["steps"]:
            current[0] = instant(step["at"])
            payload = self._payload(step["payload"], instant)
            update = runtime.process(
                AdapterEnvelope(
                    step["channel_type"],
                    step["channel"],
                    payload,
                    current[0],
                    current[0],
                )
            )
            if "expect" in step:
                self._assert_expectation(update, step["expect"])

    @staticmethod
    def _payload(raw: dict[str, object], instant=at) -> dict[str, object]:
        payload = deepcopy(raw)
        after = payload.get("after")
        if isinstance(after, dict):
            if "start_offset" in after:
                after["start_time"] = instant(after.pop("start_offset")).timestamp()
            if "frame_offset" in after:
                after["frame_time"] = instant(after.pop("frame_offset")).timestamp()
            if "end_offset" in after:
                after["end_time"] = instant(after.pop("end_offset")).timestamp()
            snapshot = after.get("snapshot")
            if isinstance(snapshot, dict) and "frame_offset" in snapshot:
                snapshot["frame_time"] = instant(snapshot.pop("frame_offset")).timestamp()
        if "timestamp_offset" in payload:
            payload["timestamp"] = instant(payload.pop("timestamp_offset")).timestamp()
        return payload

    def _assert_expectation(self, update, expected: dict[str, object]) -> None:
        if "count" in expected:
            self.assertEqual((update.snapshot.count_minimum, update.snapshot.count_maximum), tuple(expected["count"]))
        self.assertEqual(len(update.detections), expected.get("detections", 1 if "detection" in expected else 0))
        if "detection" in expected:
            detection = update.detections[0]
            values = {"area": detection.location.area if detection.location else None,
                      "image_area": detection.image.area if detection.image else None,
                      "image_at": detection.image.observed_at.isoformat() if detection.image else None}
            for key, value in expected["detection"].items():
                self.assertEqual(values[key], value)
        if "status" in expected:
            self.assertEqual(update.detections[0].status, expected["status"])
        if "presence" in expected:
            wanted = expected["presence"]
            matching = [
                presence
                for presence in update.snapshot.presences
                if presence.kind.value == wanted["kind"]
                and presence.classification == wanted.get("classification")
                and presence.identity == wanted.get("identity")
                and presence.location is not None
                and presence.location.area == wanted["area"]
            ]
            self.assertEqual(len(matching), 1)
        if "device" in expected:
            wanted = expected["device"]
            matching = [
                device
                for device in update.snapshot.devices
                if device.linked_identity == wanted["identity"]
                and device.location is not None
                and device.location.area == wanted["area"]
            ]
            self.assertEqual(len(matching), 1)


if __name__ == "__main__":
    unittest.main()
