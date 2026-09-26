"""Bounded, idempotent evidence storage with per-dimension revisions."""

from __future__ import annotations

from collections import defaultdict, deque
from dataclasses import dataclass, replace
from datetime import datetime
from typing import Callable, Iterable

from .model import Observation, ObservationStatus, RevisionDimension, RevisionStamp


ALL_DIMENSIONS = tuple(RevisionDimension)


@dataclass(frozen=True, slots=True)
class StoreUpdate:
    key: tuple[str, str]
    changed: bool
    created: bool
    global_revision: int
    record_revision: int
    changed_dimensions: tuple[RevisionDimension, ...] = ()
    rejected_dimensions: tuple[RevisionDimension, ...] = ()


@dataclass(frozen=True, slots=True)
class StoredObservation:
    observation: Observation
    record_revision: int
    dimension_revisions: dict[RevisionDimension, RevisionStamp]


class EvidenceStore:
    """Owns normalized evidence but contains no transport or HA behavior."""

    def __init__(self, *, max_records: int = 2_000, max_history_per_record: int = 16) -> None:
        if max_records < 1 or max_history_per_record < 1:
            raise ValueError("store bounds must be positive")
        self._max_records = max_records
        self._records: dict[tuple[str, str], StoredObservation] = {}
        self._history: dict[tuple[str, str], deque[StoreUpdate]] = defaultdict(
            lambda: deque(maxlen=max_history_per_record)
        )
        self._global_revision = 0

    @property
    def revision(self) -> int:
        return self._global_revision

    def advance_revision(self) -> int:
        """Advance the publication revision without mutating stored evidence."""
        self._global_revision += 1
        return self._global_revision

    def get(self, source_id: str, observation_id: str) -> StoredObservation | None:
        return self._records.get((source_id, observation_id))

    def values(self) -> tuple[Observation, ...]:
        return tuple(record.observation for record in self._records.values())

    def active(self) -> tuple[Observation, ...]:
        return tuple(
            record.observation
            for record in self._records.values()
            if record.observation.status is ObservationStatus.ACTIVE
        )

    def by_event(self, event_id: str) -> tuple[Observation, ...]:
        return tuple(
            record.observation
            for record in self._records.values()
            if record.observation.event_id == event_id
        )

    def history(self, source_id: str, observation_id: str) -> tuple[StoreUpdate, ...]:
        return tuple(self._history.get((source_id, observation_id), ()))

    def remove_source(self, source_id: str) -> tuple[tuple[str, str], ...]:
        """Invalidate one adapter without affecting evidence from other sources."""
        keys = tuple(key for key in self._records if key[0] == source_id)
        if not keys:
            return ()
        for key in keys:
            self._records.pop(key, None)
            self._history.pop(key, None)
        self._global_revision += 1
        return keys

    def remove_where(
        self,
        predicate: Callable[[Observation], bool],
    ) -> tuple[tuple[str, str], ...]:
        """Invalidate matching evidence while preserving unrelated sources."""
        keys = tuple(
            key
            for key, record in self._records.items()
            if predicate(record.observation)
        )
        if not keys:
            return ()
        for key in keys:
            self._records.pop(key, None)
            self._history.pop(key, None)
        self._global_revision += 1
        return keys

    def upsert(self, incoming: Observation) -> StoreUpdate:
        key = incoming.key
        current = self._records.get(key)
        incoming_revisions = self._effective_revisions(incoming)
        if current is None:
            self._global_revision += 1
            stored=StoredObservation(incoming, 1, incoming_revisions)
            self._records[key]=stored
            update=StoreUpdate(
                key=key,
                changed=True,
                created=True,
                global_revision=self._global_revision,
                record_revision=1,
                changed_dimensions=ALL_DIMENSIONS,
            )
            self._history[key].append(update)
            self._evict_if_needed()
            return update

        accepted: list[RevisionDimension] = []
        rejected: list[RevisionDimension] = []
        accepted_changes: dict[str, object] = {}
        merged_revisions = dict(current.dimension_revisions)
        dimensions = self._updated_dimensions(incoming)
        for dimension in dimensions:
            candidate_revision = incoming_revisions[dimension]
            existing_revision = current.dimension_revisions[dimension]
            candidate_value = self._dimension_value(incoming, dimension)
            existing_value = self._dimension_value(current.observation, dimension)
            if candidate_revision > existing_revision:
                if candidate_value != existing_value:
                    accepted.append(dimension)
                    accepted_changes.update(self._dimension_changes(incoming, dimension))
                merged_revisions[dimension]=candidate_revision
            elif candidate_revision == existing_revision:
                if candidate_value != existing_value:
                    rejected.append(dimension)
            elif candidate_value != existing_value:
                rejected.append(dimension)

        if not accepted:
            update=StoreUpdate(
                key=key,
                changed=False,
                created=False,
                global_revision=self._global_revision,
                record_revision=current.record_revision,
                rejected_dimensions=tuple(rejected),
            )
            self._history[key].append(update)
            return update

        # Apply all accepted dimensions together. Some domain invariants span
        # multiple dimensions: a zero count and an ended lifecycle are valid
        # as a pair but invalid if either one is materialized first.
        merged = replace(
            current.observation,
            **accepted_changes,
            received_at=max(current.observation.received_at, incoming.received_at),
            revisions=merged_revisions,
        )
        self._global_revision += 1
        record_revision=current.record_revision+1
        self._records[key]=StoredObservation(merged,record_revision,merged_revisions)
        update=StoreUpdate(
            key=key,
            changed=True,
            created=False,
            global_revision=self._global_revision,
            record_revision=record_revision,
            changed_dimensions=tuple(accepted),
            rejected_dimensions=tuple(rejected),
        )
        self._history[key].append(update)
        return update

    def ingest(self, observations: Iterable[Observation]) -> tuple[StoreUpdate, ...]:
        return tuple(self.upsert(observation) for observation in observations)

    @staticmethod
    def _effective_revisions(observation: Observation) -> dict[RevisionDimension, RevisionStamp]:
        revisions=dict(observation.revisions)
        for dimension in ALL_DIMENSIONS:
            if dimension in revisions:
                continue
            observed_at={
                RevisionDimension.EVENT_TIME: observation.detected_at,
                RevisionDimension.IDENTITY: observation.identity.observed_at if observation.identity else observation.received_at,
                RevisionDimension.LOCATION: observation.location.observed_at if observation.location else observation.received_at,
                RevisionDimension.CLASSIFICATION: observation.detected_at,
                RevisionDimension.COUNT: observation.count.observed_at if observation.count else observation.received_at,
                RevisionDimension.LIFECYCLE: observation.ended_at or observation.active_since or observation.received_at,
                RevisionDimension.IMAGE: observation.image.observed_at if observation.image else observation.received_at,
                RevisionDimension.DIAGNOSTICS: observation.received_at,
            }[dimension]
            revisions[dimension]=RevisionStamp(0,observed_at)
        return revisions

    @staticmethod
    def _updated_dimensions(observation: Observation) -> tuple[RevisionDimension, ...]:
        """Return the dimensions carried by an update envelope.

        Explicit revision stamps are the authoritative update mask.  When an
        adapter omits them, only non-empty claims plus the immutable event
        identity participate.  Consequently, a late identity-only envelope
        cannot accidentally clear an earlier location.  Clearing a dimension
        remains possible by sending ``None`` with an explicit newer revision.
        """
        if observation.revisions:
            return tuple(
                dimension for dimension in ALL_DIMENSIONS if dimension in observation.revisions
            )

        dimensions = [
            RevisionDimension.EVENT_TIME,
            RevisionDimension.CLASSIFICATION,
            RevisionDimension.LIFECYCLE,
        ]
        if observation.identity is not None:
            dimensions.append(RevisionDimension.IDENTITY)
        if observation.location is not None:
            dimensions.append(RevisionDimension.LOCATION)
        if observation.count is not None:
            dimensions.append(RevisionDimension.COUNT)
        if observation.image is not None:
            dimensions.append(RevisionDimension.IMAGE)
        if observation.source_diagnostics:
            dimensions.append(RevisionDimension.DIAGNOSTICS)
        return tuple(dimensions)

    @staticmethod
    def _dimension_value(observation: Observation, dimension: RevisionDimension):
        return {
            RevisionDimension.EVENT_TIME: observation.detected_at,
            RevisionDimension.IDENTITY: observation.identity,
            RevisionDimension.LOCATION: observation.location,
            RevisionDimension.CLASSIFICATION: (observation.target_kind,observation.classification),
            RevisionDimension.COUNT: observation.count,
            RevisionDimension.LIFECYCLE: (observation.status,observation.active_since,observation.ended_at),
            RevisionDimension.IMAGE: observation.image,
            RevisionDimension.DIAGNOSTICS: observation.source_diagnostics,
        }[dimension]

    @staticmethod
    def _dimension_changes(
        incoming: Observation,
        dimension: RevisionDimension,
    ) -> dict[str, object]:
        if dimension is RevisionDimension.EVENT_TIME:
            return {"detected_at": incoming.detected_at}
        if dimension is RevisionDimension.IDENTITY:
            return {"identity": incoming.identity}
        if dimension is RevisionDimension.LOCATION:
            return {"location": incoming.location}
        if dimension is RevisionDimension.CLASSIFICATION:
            return {
                "target_kind": incoming.target_kind,
                "classification": incoming.classification,
            }
        if dimension is RevisionDimension.COUNT:
            return {"count": incoming.count}
        if dimension is RevisionDimension.LIFECYCLE:
            return {
                "status": incoming.status,
                "active_since": incoming.active_since,
                "ended_at": incoming.ended_at,
            }
        if dimension is RevisionDimension.IMAGE:
            return {"image": incoming.image}
        if dimension is RevisionDimension.DIAGNOSTICS:
            return {"source_diagnostics": incoming.source_diagnostics}
        raise AssertionError(f"unsupported dimension: {dimension}")

    def _evict_if_needed(self) -> None:
        excess = len(self._records) - self._max_records
        if excess <= 0:
            return
        ordered = sorted(
            self._records,
            key=lambda key: (
                self._records[key].observation.status is ObservationStatus.ACTIVE,
                self._records[key].observation.received_at,
            ),
        )
        for key in ordered[:excess]:
            self._records.pop(key, None)
            self._history.pop(key, None)
