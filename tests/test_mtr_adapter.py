from __future__ import annotations

import unittest

from presence_engine.adapters import AdapterEnvelope, MTRCountAdapter
from presence_engine.configuration import AdapterType, SourceDefinition

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

    def _parse(self, entity_id: str, value: int, second: int):
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


if __name__ == "__main__":
    unittest.main()
