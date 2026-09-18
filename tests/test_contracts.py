from __future__ import annotations

import unittest
from datetime import datetime

from presence_engine import CountClaim, Observation, SourceRef, TargetKind

from helpers import at


class ContractTests(unittest.TestCase):
    def test_rejects_naive_times(self) -> None:
        with self.assertRaises(ValueError):
            Observation(
                observation_id="event-a",
                source=SourceRef("source-a","test"),
                received_at=datetime(2030,1,1),
                detected_at=at(),
                target_kind=TargetKind.PERSON,
            )

    def test_count_is_an_interval_not_an_implicit_exact_value(self) -> None:
        claim=CountClaim(1,3,at(),stable=False)
        self.assertEqual((claim.minimum,claim.maximum),(1,3))

    def test_invalid_interval_is_rejected(self) -> None:
        with self.assertRaises(ValueError):
            CountClaim(2,1,at(),stable=True)


if __name__ == "__main__":
    unittest.main()

