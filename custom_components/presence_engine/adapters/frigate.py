"""Adapters for documented Frigate 0.18 MQTT payloads."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Mapping

from .base import AdapterEnvelope, AdapterResult
from ..configuration import CameraDefinition, SourceDefinition
from ..engine import (
    CameraGeometry,
    CountClaim,
    GeometryContext,
    IdentityClaim,
    ImageReference,
    Observation,
    ObservationStatus,
    Quality,
    RevisionDimension,
    RevisionStamp,
    SourceRef,
    TargetKind,
    resolve_camera_location,
)
from ..temporal import TemporalCameraRegistry


ANIMAL_LABELS = frozenset({"bird", "cat", "dog", "horse"})


class FrigateEventAdapter:
    """Normalize `frigate/events` without querying Frigate again."""

    def __init__(
        self,
        definition: SourceDefinition,
        cameras: Mapping[str, CameraDefinition],
        contexts: TemporalCameraRegistry,
    ) -> None:
        self.source_id = definition.source_id
        self._topics = frozenset(definition.topics)
        self._definition = definition
        self._cameras = dict(cameras)
        self._contexts = contexts

    def accepts(self, envelope: AdapterEnvelope) -> bool:
        return envelope.channel_type == "mqtt" and envelope.channel in self._topics

    def parse(self, envelope: AdapterEnvelope) -> AdapterResult:
        payload = envelope.payload
        after = payload.get("after")
        if not isinstance(after, Mapping):
            return AdapterResult(ignored=True)
        event_id = _required_text(after, "id")
        camera_id = _required_text(after, "camera")
        label = _required_text(after, "label").casefold()
        allowed_labels = tuple(self._definition.options.get("labels", ()))
        if allowed_labels and label not in allowed_labels:
            return AdapterResult(ignored=True)
        detected_at = _timestamp(after.get("start_time"), envelope.observed_at)
        spatial_at = _timestamp(after.get("frame_time"), envelope.observed_at)
        end_value = after.get("end_time")
        ended_at = _timestamp(end_value, envelope.observed_at) if end_value else None
        status = (
            ObservationStatus.ENDED
            if payload.get("type") == "end" or ended_at is not None
            else ObservationStatus.ACTIVE
        )
        target_kind = (
            TargetKind.PERSON
            if label == "person"
            else TargetKind.ANIMAL
            if label in ANIMAL_LABELS
            else TargetKind.UNKNOWN_LIVING
        )
        location = self._location(camera_id, after, spatial_at)
        sequence = _sequence(spatial_at)
        observation = Observation(
            observation_id=event_id,
            source=SourceRef(
                source_id=self.source_id,
                family="frigate_event",
                native_id=camera_id,
                dependency_group=f"frigate-target:{event_id}",
                coverage_group=f"camera:{camera_id}",
            ),
            received_at=envelope.received_at,
            detected_at=detected_at,
            target_kind=target_kind,
            status=status,
            target_id=event_id,
            event_id=event_id,
            classification=label,
            location=location,
            count=CountClaim(1, 1, spatial_at, True, Quality.HIGH),
            image=ImageReference(
                reference=f"frigate:event:{event_id}",
                observed_at=spatial_at,
                area=location.area if location else None,
                event_id=event_id,
            ),
            active_since=detected_at,
            ended_at=ended_at,
            revisions={
                RevisionDimension.EVENT_TIME: RevisionStamp(1, detected_at),
                RevisionDimension.CLASSIFICATION: RevisionStamp(1, detected_at),
                RevisionDimension.LOCATION: RevisionStamp(sequence, spatial_at),
                RevisionDimension.COUNT: RevisionStamp(sequence, spatial_at),
                RevisionDimension.LIFECYCLE: RevisionStamp(
                    _sequence(ended_at or spatial_at), ended_at or spatial_at
                ),
                RevisionDimension.IMAGE: RevisionStamp(sequence, spatial_at),
            },
        )
        return AdapterResult(observations=(observation,))

    def _location(
        self,
        camera_id: str,
        after: Mapping[str, Any],
        observed_at: datetime,
    ):
        camera = self._cameras.get(camera_id)
        if camera is None:
            return None
        historical = self._contexts.at(camera_id, observed_at)
        context = GeometryContext(
            context_id=f"{camera_id}:{observed_at.isoformat()}",
            observed_at=observed_at,
            current_zones=tuple(_string_list(after.get("current_zones"))),
            entered_zones=tuple(_string_list(after.get("entered_zones"))),
            profile=historical.profile if historical else None,
            preset=historical.preset if historical else None,
            moving=historical.moving if historical else False,
            telemetry_valid=(
                historical.telemetry_valid
                if historical
                else not camera.context_entity_ids
            ),
            physical_profile_confirmed=(
                historical.physical_profile_confirmed if historical else False
            ),
        )
        return resolve_camera_location(
            context,
            CameraGeometry(
                floor=camera.floor,
                zone_to_area=camera.zone_to_area,
                profile_to_area=camera.profile_to_area,
                fixed_area=camera.fixed_area,
            ),
        )


class FrigateFaceAdapter:
    """Normalize documented face updates while enforcing configured threshold."""

    def __init__(self, definition: SourceDefinition) -> None:
        self.source_id = definition.source_id
        self._topics = frozenset(definition.topics)
        if "recognition_threshold" not in definition.options:
            raise ValueError(f"source {self.source_id} requires recognition_threshold")
        self._threshold = float(definition.options["recognition_threshold"])
        identity_map = definition.options.get("identity_map", {})
        if not isinstance(identity_map, Mapping):
            raise ValueError("identity_map must be an object")
        self._identity_map = dict(identity_map)
        if not 0 <= self._threshold <= 1:
            raise ValueError("recognition_threshold must be between zero and one")

    def accepts(self, envelope: AdapterEnvelope) -> bool:
        return envelope.channel_type == "mqtt" and envelope.channel in self._topics

    def parse(self, envelope: AdapterEnvelope) -> AdapterResult:
        payload = envelope.payload
        if payload.get("type") != "face":
            return AdapterResult(ignored=True)
        event_id = _required_text(payload, "id")
        camera_id = _required_text(payload, "camera")
        observed_at = _timestamp(payload.get("timestamp"), envelope.observed_at)
        raw_name = payload.get("name")
        score = float(payload.get("score") or 0)
        if not isinstance(raw_name, str) or not raw_name.strip() or score < self._threshold:
            # Frigate emits every recognition attempt. A rejected attempt is not
            # evidence that a previously confirmed identity became anonymous.
            return AdapterResult(ignored=True)
        raw_identity = raw_name.strip()
        identity = IdentityClaim(
            value=str(self._identity_map.get(raw_identity, raw_identity)),
            observed_at=observed_at,
            method="frigate_face_recognition",
            quality=Quality.HIGH,
            score=score,
        )
        observation = Observation(
            observation_id=f"{event_id}:face",
            source=SourceRef(
                source_id=self.source_id,
                family="frigate_face",
                native_id=camera_id,
                dependency_group=f"frigate-target:{event_id}",
            ),
            received_at=envelope.received_at,
            detected_at=observed_at,
            target_kind=TargetKind.PERSON,
            event_id=event_id,
            target_id=event_id,
            identity=identity,
            revisions={
                RevisionDimension.IDENTITY: RevisionStamp(_sequence(observed_at), observed_at)
            },
        )
        return AdapterResult(observations=(observation,))


def _required_text(payload: Mapping[str, Any], key: str) -> str:
    value = payload.get(key)
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"missing Frigate field: {key}")
    return value.strip()


def _timestamp(value: object, fallback: datetime) -> datetime:
    if isinstance(value, (int, float)):
        return datetime.fromtimestamp(float(value), tz=fallback.tzinfo)
    if isinstance(value, str) and value:
        return datetime.fromisoformat(value)
    return fallback


def _sequence(value: datetime) -> int:
    return int(value.timestamp() * 1_000_000)


def _string_list(value: object) -> tuple[str, ...]:
    if not isinstance(value, (list, tuple)):
        return ()
    return tuple(item for item in value if isinstance(item, str) and item)
