from __future__ import annotations

import unittest
from dataclasses import replace

from presence_engine.engine import (
    CountClaim,
    EvidenceStore,
    ObservationStatus,
    RevisionDimension,
    RevisionStamp,
    TargetKind,
)

from helpers import area, at, identity, observation


class EvidenceStoreTests(unittest.TestCase):
    def test_same_revision_and_payload_is_idempotent(self) -> None:
        store=EvidenceStore()
        item=observation("event-a",location=area("alpha"),identity_claim=identity())
        first=store.upsert(item)
        second=store.upsert(item)
        self.assertTrue(first.created)
        self.assertFalse(second.changed)
        self.assertEqual(store.revision,1)

    def test_late_identity_does_not_rewrite_event_time_or_location(self) -> None:
        store=EvidenceStore()
        initial=observation(
            "event-a",
            event_id="event-a",
            detected=0,
            location=area("alpha",1),
            revisions={
                RevisionDimension.EVENT_TIME:RevisionStamp(1,at(0)),
                RevisionDimension.LOCATION:RevisionStamp(1,at(1)),
            },
        )
        store.upsert(initial)
        enriched=replace(
            initial,
            received_at=at(40),
            identity=identity(seconds=40),
            revisions={
                RevisionDimension.EVENT_TIME:RevisionStamp(1,at(0)),
                RevisionDimension.LOCATION:RevisionStamp(1,at(1)),
                RevisionDimension.IDENTITY:RevisionStamp(2,at(40)),
            },
        )
        update=store.upsert(enriched)
        stored=store.get("source.event-a","event-a")
        assert stored is not None
        self.assertEqual(update.changed_dimensions,(RevisionDimension.IDENTITY,))
        self.assertEqual(stored.observation.detected_at,at(0))
        self.assertEqual(stored.observation.location.area,"alpha")
        self.assertEqual(stored.observation.identity.value,"person_a")

    def test_partial_identity_envelope_cannot_clear_existing_location(self) -> None:
        store = EvidenceStore()
        initial = observation(
            "event-a",
            event_id="event-a",
            detected=0,
            received=1,
            location=area("alpha", 1),
        )
        store.upsert(initial)
        identity_only = observation(
            "event-a",
            event_id="event-a",
            detected=0,
            received=40,
            identity_claim=identity(seconds=40),
        )

        update = store.upsert(identity_only)
        stored = store.get("source.event-a", "event-a")

        assert stored is not None
        self.assertEqual(update.changed_dimensions, (RevisionDimension.IDENTITY,))
        self.assertEqual(stored.observation.location.area, "alpha")
        self.assertEqual(stored.observation.identity.value, "person_a")

    def test_explicit_revision_can_clear_a_dimension(self) -> None:
        store = EvidenceStore()
        initial = observation(
            "event-a",
            location=area("alpha", 1),
            revisions={RevisionDimension.LOCATION: RevisionStamp(1, at(1))},
        )
        store.upsert(initial)
        cleared = replace(
            initial,
            received_at=at(2),
            location=None,
            revisions={RevisionDimension.LOCATION: RevisionStamp(2, at(2))},
        )

        update = store.upsert(cleared)
        stored = store.get("source.event-a", "event-a")

        assert stored is not None
        self.assertEqual(update.changed_dimensions, (RevisionDimension.LOCATION,))
        self.assertIsNone(stored.observation.location)

    def test_older_location_revision_is_rejected(self) -> None:
        store=EvidenceStore()
        current=observation(
            "event-a",
            location=area("beta",20),
            revisions={RevisionDimension.LOCATION:RevisionStamp(3,at(20))},
        )
        store.upsert(current)
        older=replace(
            current,
            location=area("alpha",10),
            revisions={RevisionDimension.LOCATION:RevisionStamp(2,at(10))},
        )
        update=store.upsert(older)
        stored=store.get("source.event-a","event-a")
        assert stored is not None
        self.assertFalse(update.changed)
        self.assertIn(RevisionDimension.LOCATION,update.rejected_dimensions)
        self.assertEqual(stored.observation.location.area,"beta")

    def test_count_and_lifecycle_revisions_are_applied_atomically(self) -> None:
        store = EvidenceStore()
        initial = observation(
            "area-count",
            count=CountClaim(1, 1, at(1), False),
            active_since=1,
            revisions={
                RevisionDimension.COUNT: RevisionStamp(1, at(1)),
                RevisionDimension.LIFECYCLE: RevisionStamp(1, at(1)),
            },
        )
        store.upsert(initial)
        ended = observation(
            "area-count",
            count=CountClaim(0, 0, at(2), False),
            received=2,
            active_since=1,
            status=ObservationStatus.ENDED,
            ended=2,
            revisions={
                RevisionDimension.COUNT: RevisionStamp(2, at(2)),
                RevisionDimension.LIFECYCLE: RevisionStamp(2, at(2)),
            },
        )

        update = store.upsert(ended)
        stored = store.get("source.area-count", "area-count")

        assert stored is not None
        self.assertEqual(
            update.changed_dimensions,
            (RevisionDimension.COUNT, RevisionDimension.LIFECYCLE),
        )
        self.assertEqual(stored.observation.status, ObservationStatus.ENDED)
        self.assertEqual(stored.observation.count.maximum, 0)
        self.assertEqual(stored.observation.ended_at, at(2))

    def test_source_removal_does_not_remove_other_sources(self) -> None:
        store=EvidenceStore()
        store.upsert(observation("a",source_id="source.one"))
        store.upsert(observation("b",source_id="source.two"))
        removed=store.remove_source("source.one")
        self.assertEqual(removed,(("source.one","a"),))
        self.assertIsNotNone(store.get("source.two","b"))

    def test_bounded_store_evicts_ended_before_active(self) -> None:
        store=EvidenceStore(max_records=2)
        store.upsert(observation("ended",status=ObservationStatus.ENDED,ended=1))
        store.upsert(observation("active-a"))
        store.upsert(observation("active-b",kind=TargetKind.ANIMAL))
        self.assertIsNone(store.get("source.ended","ended"))
        self.assertEqual(len(store.values()),2)


if __name__ == "__main__":
    unittest.main()
