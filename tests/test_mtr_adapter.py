from __future__ import annotations

import json
from pathlib import Path
import unittest

from presence_engine.adapters import AdapterEnvelope, MTRCountAdapter
from presence_engine.configuration import AdapterType, SourceDefinition, parse_configuration
from presence_engine.engine import EvidenceStore, FrozenClock, PresenceConfig, PresenceResolver
from presence_engine.runtime import PresenceRuntime

from helpers import at


class MTRCountAdapterTests(unittest.TestCase):
    def setUp(self) -> None:
        self.adapter = MTRCountAdapter(
            SourceDefinition(
                source_id="mtr_alpha",
                adapter=AdapterType.MTR_COUNT,
                entity_ids=("sensor.total", "sensor.zone_1", "sensor.zone_2"),
                floor="floor_alpha",
                coverage_group="mtr_alpha",
                options={
                    "total_entity_id": "sensor.total",
                    "zone_areas": {
                        "sensor.zone_1": "alpha",
                        "sensor.zone_2": "beta",
                    },
                },
            )
        )

    def _parse(self, entity_id: str, value: int | str, second: int):
        return self.adapter.parse(
            AdapterEnvelope(
                "state",
                entity_id,
                {"state": str(value), "last_changed": at(second).isoformat()},
                at(second),
                at(second),
            )
        )

    def test_total_is_not_added_again_when_targets_are_in_zones(self) -> None:
        self._parse("sensor.zone_1", 1, 0)
        self._parse("sensor.zone_2", 1, 1)
        result = self._parse("sensor.total", 2, 2)

        active = [item for item in result.observations if item.status.value == "active"]
        self.assertEqual(sum(item.count.maximum for item in active), 2)
        self.assertEqual({item.location.area for item in active}, {"alpha", "beta"})

    def test_only_remainder_outside_zones_is_floor_scoped(self) -> None:
        self._parse("sensor.zone_1", 1, 0)
        self._parse("sensor.zone_2", 0, 1)
        result = self._parse("sensor.total", 2, 2)

        outside = next(item for item in result.observations if item.observation_id == "outside_zones")
        self.assertEqual(outside.count.maximum, 1)
        self.assertEqual(outside.location.level.value, "floor")

    def test_old_empty_zones_do_not_make_a_new_multi_target_count_stable(self) -> None:
        self._parse("sensor.zone_1", 0, -100)
        self._parse("sensor.zone_2", 0, -200)
        self._parse("sensor.total", 1, -50)
        result = self._parse("sensor.total", 2, 0)
        outside = next(o for o in result.observations if o.observation_id == "outside_zones")
        self.assertEqual(outside.active_since, at(0))
        self.assertEqual(outside.count.maximum, 2)
        for second, expected in ((0, (1, 2)), (2.9, (1, 2)), (3, (2, 2))):
            resolved = PresenceResolver(PresenceConfig(), FrozenClock(at(second))).resolve(
                result.observations, revision=1)
            self.assertEqual((resolved.count_minimum, resolved.count_maximum), expected)
            self.assertEqual(resolved.presences[0].location.observed_at, at(0))

    def test_runtime_matures_count_once_and_retires_a_short_pulse_without_polling(self) -> None:
        raw = json.loads((Path(__file__).with_name("fixtures") / "mtr-zone-transitions.json").read_text(encoding="utf-8"))
        clock = [at(0)]
        runtime = PresenceRuntime(parse_configuration(raw["configuration"]), now=lambda: clock[0])
        def deliver(entity, value, second, changed=None):
            clock[0] = at(second)
            return runtime.process(AdapterEnvelope("state", entity,
                {"state": str(value), "last_changed": at(second if changed is None else changed).isoformat()},
                at(second), clock[0]))
        for entity in ("sensor.radar_zone_a", "sensor.radar_zone_b", "sensor.radar_zone_c"):
            deliver(entity, 0, -100)
        deliver("sensor.radar_total", 1, -50)
        update = deliver("sensor.radar_total", 2, 0)
        self.assertEqual((update.snapshot.count_minimum, update.snapshot.count_maximum), (1, 2))
        self.assertEqual(runtime.next_expiration(), at(3))
        deliver("sensor.radar_total", 2, 1, changed=0)
        self.assertEqual(runtime.next_expiration(), at(3))
        clock[0] = at(3)
        update = runtime.refresh()
        self.assertTrue(update.changed)
        self.assertEqual((update.snapshot.count_minimum, update.snapshot.count_maximum), (2, 2))
        self.assertFalse(update.detections)
        self.assertIsNone(runtime.next_expiration())
        self.assertFalse(runtime.refresh().changed)
        deliver("sensor.radar_total", 1, 4)
        deliver("sensor.radar_total", 2, 5)
        update = deliver("sensor.radar_total", 1, 6.9)
        self.assertEqual((update.snapshot.count_minimum, update.snapshot.count_maximum), (1, 1))
        self.assertIsNone(runtime.next_expiration())

    def test_overlapping_zones_never_exceed_total_population(self) -> None:
        self._parse("sensor.zone_1", 1, 0)
        self._parse("sensor.zone_2", 1, 1)
        result = self._parse("sensor.total", 1, 2)

        active = [item for item in result.observations if item.status.value == "active"]

        self.assertEqual(sum(item.count.maximum for item in active), 1)
        self.assertEqual(active[0].observation_id, "overlapping_zones")
        self.assertEqual(active[0].location.candidates, ("alpha", "beta"))
        self.assertEqual(active[0].location.method, "mtr_overlapping_zones")

    def test_waits_for_complete_compound_state(self) -> None:
        result = self._parse("sensor.zone_1", 1, 0)

        self.assertTrue(result.ignored)
        self.assertEqual(result.observations, ())

    def test_zone_transitions_retire_previous_buckets_in_the_store(self) -> None:
        store = EvidenceStore()
        for entity, value, second, expected in (
            ("sensor.total", 1, 0, 0),
            ("sensor.zone_1", 0, 0, 0),
            ("sensor.zone_2", 0, 0, 1),
            ("sensor.zone_1", 1, 1, 1),
            ("sensor.zone_2", 1, 1, 1),
            ("sensor.zone_1", 0, 2, 1),
            ("sensor.zone_2", 0, 2, 1),
            ("sensor.total", 0, 2, 0),
        ):
            with self.subTest(entity=entity, value=value, second=second):
                for item in self._parse(entity, value, second).observations:
                    update = store.upsert(item)
                    self.assertEqual(update.rejected_dimensions, ())
                self.assertEqual(sum(item.count.maximum for item in store.active()), expected)

    def test_each_channel_advances_even_below_the_latest_compound_time(self) -> None:
        store = EvidenceStore()
        for entity, value, second in (
            ("sensor.total", 2, 10),
            ("sensor.zone_1", 1, 1),
            ("sensor.zone_2", 0, 2),
            ("sensor.zone_2", 1, 3),
        ):
            for item in self._parse(entity, value, second).observations:
                update = store.upsert(item)
                self.assertEqual(update.rejected_dimensions, ())
        self.assertEqual(sum(item.count.maximum for item in store.active()), 2)
        self.assertEqual({item.location.area for item in store.active()}, {"alpha", "beta"})
        self.assertEqual(store.get("mtr_alpha", "area:beta").observation.location.observed_at, at(3))

    def test_duplicate_and_old_messages_do_not_overwrite_current_inputs(self) -> None:
        self._parse("sensor.total", 1, 0)
        self._parse("sensor.zone_1", 1, 3)
        self._parse("sensor.zone_2", 0, 0)
        for value, second in ((1, 3), (0, 2), ("unavailable", 2)):
            with self.subTest(value=value, second=second):
                result = self._parse("sensor.zone_1", value, second)
                self.assertTrue(result.ignored)
                self.assertEqual(result.remove_source_ids, ())
                self.assertEqual(result.observations, ())
        unavailable = self._parse("sensor.zone_1", "unavailable", 4)
        self.assertEqual(unavailable.remove_source_ids, ("mtr_alpha",))
        self.assertTrue(self._parse("sensor.zone_1", 1, 3).ignored)
        self.assertFalse(self._parse("sensor.zone_1", 1, 5).ignored)

    def test_revision_order_survives_reloading_the_adapter(self) -> None:
        store = EvidenceStore()
        states = (("sensor.total", 1, 0), ("sensor.zone_1", 1, 1), ("sensor.zone_2", 0, 2))
        for entity, value, second in states:
            for item in self._parse(entity, value, second).observations:
                store.upsert(item)
        self.setUp()
        self.adapter.restore_revision(max(
            revision.sequence for item in store.values() for revision in item.revisions.values()
        ))
        for entity, value, second in reversed(states):
            for item in self._parse(entity, value, second).observations:
                update = store.upsert(item)
                self.assertFalse(update.changed)
                self.assertEqual(update.rejected_dimensions, ())
        for item in self._parse("sensor.zone_1", 0, 3).observations:
            update = store.upsert(item)
            self.assertEqual(update.rejected_dimensions, ())
        self.assertEqual([item.observation_id for item in store.active()], ["outside_zones"])

    def test_runtime_restores_compound_clock_and_retires_old_buckets(self) -> None:
        path = Path(__file__).with_name("fixtures") / "mtr-zone-transitions.json"
        fixture = json.loads(path.read_text(encoding="utf-8"))
        configuration = parse_configuration(fixture["configuration"])
        runtime = PresenceRuntime(configuration, now=lambda: at(4))
        for step in fixture["steps"][:7]:
            runtime.process(AdapterEnvelope(
                "state", step["channel"], step["payload"], at(step["at"]), at(step["at"])
            ))
        saved = runtime.export_state()
        runtime = PresenceRuntime(configuration, now=lambda: at(4))
        runtime.restore_state(saved)
        for index in (0, 4, 2, 6):
            step = fixture["steps"][index]
            update = runtime.process(AdapterEnvelope(
                "state", step["channel"], step["payload"], at(step["at"]), at(4)
            ))
        self.assertEqual((update.snapshot.count_minimum, update.snapshot.count_maximum), (1, 1))
        self.assertEqual([item.location.area for item in update.snapshot.presences], ["alpha"])
        update = runtime.process(AdapterEnvelope(
            "state", "sensor.radar_zone_a", {"state": "0"}, at(4), at(4)
        ))
        self.assertEqual((update.snapshot.count_minimum, update.snapshot.count_maximum), (1, 1))
        self.assertEqual([item.location.area for item in update.snapshot.presences], [None])


if __name__ == "__main__":
    unittest.main()
