"""Compound adapter for one Apollo MTR total and its calibrated zones."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any, Mapping

from .base import AdapterEnvelope, AdapterResult
from .entity import INVALID_STATES
from ..configuration import SourceDefinition
from ..engine import (
    CountClaim,
    Observation,
    ObservationStatus,
    Quality,
    RevisionDimension,
    RevisionStamp,
    SourceRef,
    SpatialClaim,
    SpatialLevel,
    TargetKind,
)


@dataclass(frozen=True, slots=True)
class _CountState:
    value: int
    observed_at: datetime
    active_since: datetime


class MTRCountAdapter:
    """Publish zones plus only the remainder outside every calibrated zone."""

    def __init__(self, definition: SourceDefinition) -> None:
        self.source_id = definition.source_id
        self._definition = definition
        self._entities = frozenset(definition.entity_ids)
        self._total_entity_id = str(definition.options["total_entity_id"])
        self._zone_areas = dict(definition.options["zone_areas"])
        self._states: dict[str, _CountState] = {}

    def accepts(self, envelope: AdapterEnvelope) -> bool:
        return envelope.channel_type == "state" and envelope.channel in self._entities

    def parse(self, envelope: AdapterEnvelope) -> AdapterResult:
        raw_state = str(envelope.payload.get("state", ""))
        if raw_state.casefold() in INVALID_STATES:
            self._states.pop(envelope.channel, None)
            return AdapterResult(remove_source_ids=(self.source_id,))
        value = max(0, int(float(raw_state)))
        self._states[envelope.channel] = _CountState(
            value=value,
            observed_at=envelope.observed_at,
            active_since=_state_time(envelope.payload, envelope.observed_at),
        )
        if any(entity_id not in self._states for entity_id in self._entities):
            return AdapterResult(ignored=True)
        total = self._states.get(self._total_entity_id)
        assert total is not None
        zone_states = {
            entity_id: self._states[entity_id] for entity_id in self._zone_areas
        }
        zone_total = sum(state.value for state in zone_states.values())
        observations: list[Observation] = []

        if zone_total > total.value:
            # A physical target can occupy overlapping logical zones. The total
            # is the hard population bound; competing areas remain candidates.
            observations.extend(
                self._zero_zone_buckets(total, envelope.received_at)
            )
            observations.append(
                self._ambiguous_observation(
                    total.value,
                    self._combine_states((*zone_states.values(), total)),
                    envelope.received_at,
                )
            )
            outside_value = 0
        else:
            observations.extend(
                self._area_bucket_observations(zone_states, envelope.received_at)
            )
            observations.append(
                self._ambiguous_observation(0, total, envelope.received_at)
            )
            outside_value = total.value - zone_total
        observations.append(
            self._outside_observation(outside_value, total, envelope.received_at)
        )
        return AdapterResult(observations=tuple(observations))

    def _area_bucket_observations(
        self,
        zone_states: Mapping[str, _CountState],
        received_at: datetime,
    ) -> tuple[Observation, ...]:
        buckets: dict[str | None, list[_CountState]] = {}
        for entity_id, area in self._zone_areas.items():
            buckets.setdefault(area if isinstance(area, str) and area else None, []).append(
                zone_states[entity_id]
            )
        observations = []
        for area, states in sorted(buckets.items(), key=lambda item: item[0] or ""):
            combined = self._combine_states(states)
            value = sum(state.value for state in states)
            location = (
                SpatialClaim(
                    level=SpatialLevel.AREA,
                    area=area,
                    floor=self._definition.floor,
                    candidates=(area,),
                    method="mtr_calibrated_zone",
                    quality=Quality.HIGH,
                    observed_at=combined.observed_at,
                )
                if area is not None
                else SpatialClaim(
                    level=SpatialLevel.FLOOR,
                    floor=self._definition.floor,
                    method="mtr_ambiguous_zone",
                    quality=Quality.MEDIUM,
                    observed_at=combined.observed_at,
                )
            )
            observations.append(
                self._observation(
                    f"area:{area or 'floor'}",
                    value,
                    combined,
                    received_at,
                    location,
                )
            )
        return tuple(observations)

    def _zero_zone_buckets(
        self,
        state: _CountState,
        received_at: datetime,
    ) -> tuple[Observation, ...]:
        empty_states = {
            entity_id: _CountState(0, state.observed_at, state.active_since)
            for entity_id in self._zone_areas
        }
        return self._area_bucket_observations(empty_states, received_at)

    def _ambiguous_observation(
        self,
        value: int,
        state: _CountState,
        received_at: datetime,
    ) -> Observation:
        candidates = tuple(
            sorted(
                {
                    area
                    for area in self._zone_areas.values()
                    if isinstance(area, str) and area
                }
            )
        )
        return self._observation(
            "overlapping_zones",
            value,
            state,
            received_at,
            SpatialClaim(
                level=SpatialLevel.FLOOR,
                floor=self._definition.floor,
                candidates=candidates,
                method="mtr_overlapping_zones",
                quality=Quality.MEDIUM,
                observed_at=state.observed_at,
            ),
        )

    def _outside_observation(
        self,
        value: int,
        state: _CountState,
        received_at: datetime,
    ) -> Observation:
        return self._observation(
            "outside_zones",
            value,
            state,
            received_at,
            SpatialClaim(
                level=SpatialLevel.FLOOR,
                floor=self._definition.floor,
                method="mtr_outside_calibrated_zones",
                quality=Quality.MEDIUM,
                observed_at=state.observed_at,
            ),
        )

    def _observation(
        self,
        observation_id: str,
        value: int,
        state: _CountState,
        received_at: datetime,
        location: SpatialClaim,
    ) -> Observation:
        active = value > 0
        sequence = int(state.observed_at.timestamp() * 1_000_000)
        revision = RevisionStamp(sequence, state.observed_at)
        dependency_group = f"{self.source_id}:{observation_id}"
        return Observation(
            observation_id=observation_id,
            source=SourceRef(
                source_id=self.source_id,
                family="mtr_count",
                native_id=observation_id,
                dependency_group=dependency_group,
                coverage_group=self._definition.coverage_group,
            ),
            received_at=received_at,
            detected_at=state.observed_at,
            target_kind=TargetKind.UNKNOWN_LIVING,
            status=ObservationStatus.ACTIVE if active else ObservationStatus.ENDED,
            target_id=None,
            location=location,
            count=CountClaim(value, value, state.observed_at, False, location.quality),
            active_since=state.active_since,
            ended_at=None if active else state.observed_at,
            revisions={
                RevisionDimension.LOCATION: revision,
                RevisionDimension.COUNT: revision,
                RevisionDimension.LIFECYCLE: revision,
            },
        )

    @staticmethod
    def _combine_states(states: Any) -> _CountState:
        values = tuple(states)
        return _CountState(
            value=sum(state.value for state in values),
            observed_at=max(state.observed_at for state in values),
            active_since=min(state.active_since for state in values),
        )


def _state_time(payload: Mapping[str, Any], fallback: datetime) -> datetime:
    value = payload.get("last_changed")
    if isinstance(value, datetime):
        return value
    if isinstance(value, str) and value:
        return datetime.fromisoformat(value)
    return fallback
