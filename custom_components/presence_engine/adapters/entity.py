"""Adapters for exact Home Assistant entity state subscriptions."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Mapping

from .base import AdapterEnvelope, AdapterResult
from ..configuration import AdapterType, CameraDefinition, SourceDefinition
from ..engine import (
    CountClaim,
    IdentityClaim,
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
from ..temporal import TemporalCameraRegistry


INVALID_STATES = frozenset({"unknown", "unavailable", "none", ""})
ABSENT_AREA_STATES = frozenset({"not_home", "away"})


class PTZContextAdapter:
    """Maintain historical PTZ context from exact state entities."""

    def __init__(
        self,
        camera: CameraDefinition,
        registry: TemporalCameraRegistry,
    ) -> None:
        self.source_id = f"ptz-context:{camera.camera_id}"
        self._camera = camera
        self._registry = registry
        self._roles = {
            entity_id: role
            for entity_id, role in (
                (camera.profile_entity_id, "profile"),
                (camera.preset_entity_id, "preset"),
                (camera.movement_entity_id, "movement"),
            )
            if entity_id is not None
        }

    def accepts(self, envelope: AdapterEnvelope) -> bool:
        return envelope.channel_type == "state" and envelope.channel in self._roles

    def parse(self, envelope: AdapterEnvelope) -> AdapterResult:
        state = str(envelope.payload.get("state", ""))
        role = self._roles[envelope.channel]
        if state.casefold() in INVALID_STATES:
            state = "unavailable" if role == "movement" else ""
        self._registry.update(
            self._camera.camera_id,
            role=role,
            state=state,
            observed_at=envelope.observed_at,
        )
        return AdapterResult(context_changed=True)


class EntityStateAdapter:
    """Normalize one configured entity family without scanning HA state."""

    def __init__(self, definition: SourceDefinition) -> None:
        self.source_id = definition.source_id
        self._definition = definition
        self._entities = frozenset(definition.entity_ids)

    def accepts(self, envelope: AdapterEnvelope) -> bool:
        return envelope.channel_type == "state" and envelope.channel in self._entities

    def parse(self, envelope: AdapterEnvelope) -> AdapterResult:
        state = str(envelope.payload.get("state", ""))
        normalized = state.casefold()
        if normalized in INVALID_STATES:
            return AdapterResult(remove_source_ids=(self.source_id,))
        if self._definition.adapter is AdapterType.BERMUDA_AREA:
            return self._bermuda(envelope, state)
        if self._definition.adapter is AdapterType.COUNT:
            return self._count(envelope, state)
        if self._definition.adapter is AdapterType.BINARY_PRESENCE:
            return self._binary(envelope, normalized)
        if self._definition.adapter is AdapterType.PERSON_HOME:
            return self._person_home(envelope, normalized)
        if self._definition.adapter is AdapterType.AUXILIARY_ACTIVITY:
            return AdapterResult(ignored=True)
        raise ValueError(f"unsupported entity adapter: {self._definition.adapter.value}")

    def _bermuda(self, envelope: AdapterEnvelope, state: str) -> AdapterResult:
        if state.casefold() in ABSENT_AREA_STATES:
            return AdapterResult(remove_source_ids=(self.source_id,))
        area_map = self._definition.options.get("area_map", {})
        area = area_map.get(state, state.casefold().replace(" ", "_"))
        if not isinstance(area, str) or not area:
            return AdapterResult(ignored=True)
        identity_value = self._definition.identity
        identity = (
            IdentityClaim(
                value=identity_value,
                observed_at=envelope.observed_at,
                method="registered_device_owner",
                quality=Quality.HIGH,
            )
            if identity_value
            else None
        )
        location = SpatialClaim(
            level=SpatialLevel.AREA,
            area=area,
            floor=self._definition.floor,
            candidates=(area,),
            method="bermuda_nearest_scanner",
            quality=self._definition.spatial_quality,
            observed_at=envelope.observed_at,
        )
        observation = self._observation(
            envelope,
            kind=TargetKind.DEVICE,
            identity=identity,
            location=location,
            count=None,
            active=True,
        )
        return AdapterResult(observations=(observation,))

    def _count(self, envelope: AdapterEnvelope, state: str) -> AdapterResult:
        value = int(float(state))
        active = value > 0
        location = self._configured_location(envelope.observed_at)
        observation = self._observation(
            envelope,
            kind=self._definition.target_kind,
            identity=None,
            location=location,
            count=CountClaim(
                minimum=value,
                maximum=value,
                observed_at=envelope.observed_at,
                stable=False,
                quality=self._definition.spatial_quality,
            ),
            active=active,
        )
        return AdapterResult(observations=(observation,))

    def _binary(self, envelope: AdapterEnvelope, state: str) -> AdapterResult:
        if state not in {"on", "off"}:
            raise ValueError(f"binary source {self.source_id} received {state!r}")
        observation = self._observation(
            envelope,
            kind=self._definition.target_kind,
            identity=None,
            location=self._configured_location(envelope.observed_at),
            count=(
                CountClaim(1, 1, envelope.observed_at, True, self._definition.spatial_quality)
                if state == "on"
                else CountClaim(0, 0, envelope.observed_at, True, self._definition.spatial_quality)
            ),
            active=state == "on",
        )
        return AdapterResult(observations=(observation,))

    def _person_home(self, envelope: AdapterEnvelope, state: str) -> AdapterResult:
        active = state == "home"
        identity = (
            IdentityClaim(
                value=self._definition.identity,
                observed_at=envelope.observed_at,
                method="home_scope",
                quality=Quality.MEDIUM,
            )
            if self._definition.identity
            else None
        )
        location = SpatialClaim(
            level=SpatialLevel.HOME,
            method="home_scope",
            quality=Quality.LOW,
            observed_at=envelope.observed_at,
        )
        observation = self._observation(
            envelope,
            kind=TargetKind.PERSON,
            identity=identity,
            location=location,
            count=CountClaim(1 if active else 0, 1 if active else 0, envelope.observed_at, True),
            active=active,
        )
        return AdapterResult(observations=(observation,))

    def _configured_location(self, observed_at: datetime) -> SpatialClaim:
        if self._definition.area:
            return SpatialClaim(
                level=SpatialLevel.AREA,
                area=self._definition.area,
                floor=self._definition.floor,
                candidates=(self._definition.area,),
                method=str(self._definition.options.get("location_method", "configured_area")),
                quality=self._definition.spatial_quality,
                observed_at=observed_at,
            )
        return SpatialClaim(
            level=SpatialLevel.FLOOR,
            floor=self._definition.floor,
            method=str(self._definition.options.get("location_method", "configured_floor")),
            quality=self._definition.spatial_quality,
            observed_at=observed_at,
        )

    def _observation(
        self,
        envelope: AdapterEnvelope,
        *,
        kind: TargetKind,
        identity: IdentityClaim | None,
        location: SpatialClaim,
        count: CountClaim | None,
        active: bool,
    ) -> Observation:
        sequence = int(envelope.observed_at.timestamp() * 1_000_000)
        status = ObservationStatus.ACTIVE if active else ObservationStatus.ENDED
        revisions = {
            RevisionDimension.LOCATION: RevisionStamp(sequence, envelope.observed_at),
            RevisionDimension.LIFECYCLE: RevisionStamp(sequence, envelope.observed_at),
        }
        if count is not None:
            revisions[RevisionDimension.COUNT] = RevisionStamp(sequence, envelope.observed_at)
        if identity is not None:
            revisions[RevisionDimension.IDENTITY] = RevisionStamp(sequence, envelope.observed_at)
        return Observation(
            observation_id=self.source_id,
            source=SourceRef(
                source_id=self.source_id,
                family=self._definition.adapter.value,
                native_id=envelope.channel,
                dependency_group=self._definition.dependency_group,
                coverage_group=self._definition.coverage_group,
            ),
            received_at=envelope.received_at,
            detected_at=envelope.observed_at,
            target_kind=kind,
            status=status,
            target_id=(
                str(self._definition.options["target_id"])
                if "target_id" in self._definition.options
                else identity.value
                if identity is not None
                else self.source_id
                if kind is TargetKind.DEVICE
                else None
            ),
            identity=identity,
            location=location,
            count=count,
            active_since=_state_time(envelope.payload, "last_changed", envelope.observed_at),
            ended_at=envelope.observed_at if not active else None,
            revisions=revisions,
        )


def _state_time(payload: Mapping[str, Any], key: str, fallback: datetime) -> datetime:
    value = payload.get(key)
    if isinstance(value, datetime):
        return value
    if isinstance(value, str) and value:
        return datetime.fromisoformat(value)
    return fallback
