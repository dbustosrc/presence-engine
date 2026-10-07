"""Adapters for exact Home Assistant entity state subscriptions."""

from __future__ import annotations

from datetime import datetime
from dataclasses import replace
import math
from typing import Any, Mapping

from .base import (
    AdapterEnvelope,
    AdapterResult,
    CameraAvailability,
    SourceAvailability,
)
from ..configuration import AdapterType, CameraDefinition, SourceDefinition
from ..engine import (
    CountClaim,
    DeviceSignalSample,
    GeographicPosition,
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
    require_aware,
)
from ..temporal import TemporalCameraRegistry
from ..radar import radar_sample


INVALID_STATES = frozenset({"unknown", "unavailable", "none", ""})
ABSENT_AREA_STATES = frozenset({"not_home", "away"})


class CameraAvailabilityAdapter:
    """Reduce exact camera health entities to one evidence availability state."""

    def __init__(self, camera: CameraDefinition) -> None:
        self.source_id = f"camera-health:{camera.camera_id}"
        self._camera_id = camera.camera_id
        self._entities = frozenset(camera.availability_entity_ids)
        self._unavailable_states = frozenset(camera.availability_unavailable_states)
        self._states: dict[str, str | None] = {
            entity_id: None for entity_id in camera.availability_entity_ids
        }

    def accepts(self, envelope: AdapterEnvelope) -> bool:
        return envelope.channel_type == "state" and envelope.channel in self._entities

    def parse(self, envelope: AdapterEnvelope) -> AdapterResult:
        self._states[envelope.channel] = str(envelope.payload.get("state", "")).casefold()
        available = all(
            state is not None and state not in self._unavailable_states
            for state in self._states.values()
        )
        return AdapterResult(
            camera_availability=(CameraAvailability(self._camera_id, available),)
        )


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
                (camera.telemetry_entity_id, "telemetry"),
            )
            if entity_id is not None
        }

    def accepts(self, envelope: AdapterEnvelope) -> bool:
        return envelope.channel_type == "state" and envelope.channel in self._roles

    def parse(self, envelope: AdapterEnvelope) -> AdapterResult:
        state = str(envelope.payload.get("state", ""))
        role = self._roles[envelope.channel]
        if role == "telemetry":
            attributes = envelope.payload.get("attributes", {})
            if not isinstance(attributes, Mapping):
                raise ValueError("telemetry attributes must be a mapping")
            intervals = attributes.get("stable_intervals", [])
            if not isinstance(intervals, list):
                raise ValueError("stable_intervals must be a list")
            changed = False
            pending = []
            for item in intervals[-64:]:
                if not isinstance(item, Mapping) or not isinstance(item.get("destination"), str):
                    raise ValueError("invalid measured destination")
                start = datetime.fromisoformat(item["start"])
                end = datetime.fromisoformat(item["end"])
                require_aware(start, "position interval start")
                require_aware(end, "position interval end")
                if end > envelope.received_at:
                    raise ValueError("position measurement is in the future")
                if not item["destination"] or not 0 < (end - start).total_seconds() <= 3:
                    raise ValueError("invalid measured position interval")
                pending.append((item["destination"], start, end))
            for destination, start, end in pending:
                changed = self._registry.record_interval(self._camera.camera_id,
                                                        destination=destination, start=start, end=end) or changed
            return AdapterResult(context_changed=changed)
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
        self._wifi_observation: Observation | None = None
        self._gps_observation: Observation | None = None

    def accepts(self, envelope: AdapterEnvelope) -> bool:
        return envelope.channel_type == "state" and envelope.channel in self._entities

    def parse(self, envelope: AdapterEnvelope) -> AdapterResult:
        state = str(envelope.payload.get("state", ""))
        normalized = state.casefold()
        if envelope.channel in self._definition.options.get("radar_channels", {}):
            return AdapterResult(radar_signals=(radar_sample(self._definition, envelope),))
        if self._definition.adapter is AdapterType.WIFI_TRACKER:
            return self._wifi_tracker(envelope, normalized)
        if self._definition.adapter is AdapterType.GPS_TRACKER:
            return self._gps_tracker(envelope, state)
        if self._definition.adapter is AdapterType.BERMUDA_SIGNAL:
            return self._device_signal(envelope, state)
        if self._definition.adapter is AdapterType.SOURCE_HEALTH:
            return self._source_health(normalized)
        if normalized in INVALID_STATES:
            return AdapterResult(
                remove_source_ids=(self.source_id,),
                source_availability=(SourceAvailability(self.source_id, False),),
            )
        if self._definition.adapter is AdapterType.BERMUDA_AREA:
            return self._bermuda(envelope, state)
        if self._definition.adapter is AdapterType.COUNT:
            return self._count(envelope, state)
        if self._definition.adapter is AdapterType.BINARY_PRESENCE:
            return self._binary(envelope, normalized)
        if self._definition.adapter is AdapterType.PERSON_HOME:
            return self._person_home(envelope, normalized)
        if self._definition.adapter is AdapterType.AUXILIARY_ACTIVITY:
            active = normalized in {s.casefold() for s in self._definition.options.get("active_states", ("on", "playing"))}
            origin = self._definition.options.get("activity_origin", "unknown")
            item = self._observation(envelope, kind=TargetKind.DEVICE, identity=None, count=None, active=active,
                location=replace(self._configured_location(envelope.observed_at), method="auxiliary_activity", quality=Quality.LOW))
            return AdapterResult(observations=(replace(item, classification=envelope.channel.split(".")[0],
                source_diagnostics={"presence_derived":origin == "presence_derived", "origin_unknown":origin == "unknown"},
                revisions={**item.revisions, RevisionDimension.DIAGNOSTICS:RevisionStamp(
                    int(envelope.observed_at.timestamp()*1_000_000), envelope.observed_at)}),))
        raise ValueError(f"unsupported entity adapter: {self._definition.adapter.value}")

    def restore_gps_observation(self, observation: Observation | None) -> bool:
        """Deduplicate only a saved device measurement with the current binding."""
        self._gps_observation = None
        if observation is None:
            return True
        d = self._definition
        p = observation.geographic_position
        if (observation.source.family != "gps_tracker" or observation.target_kind is not TargetKind.DEVICE
                or observation.observation_id != self.source_id or observation.target_id != d.options["device_id"]
                or observation.source.native_id not in self._entities or p is None
                or p.timestamp_attribute != d.options.get("timestamp_attribute")
                or observation.status is not ObservationStatus.ACTIVE or observation.location is None
                or observation.location.level is not (SpatialLevel.HOME if p.native_zone.casefold() == "home" else SpatialLevel.UNKNOWN)
                or observation.location.area is not None or observation.location.floor is not None or observation.location.candidates
                or observation.location.method != ("gps_device_home" if p.native_zone.casefold() == "home" else "gps_device_position")
                or observation.location.observed_at != p.observed_at or observation.detected_at != p.observed_at
                or (observation.identity.value if observation.identity else None) != d.identity
                or observation.count is not None or observation.event_id is not None or observation.image is not None):
            return False
        self._gps_observation = observation
        return True

    def _gps_tracker(self, envelope: AdapterEnvelope, state: str) -> AdapterResult:
        if state.casefold() in INVALID_STATES:
            self._gps_observation = None
            return AdapterResult(remove_source_ids=(self.source_id,), source_availability=(SourceAvailability(self.source_id, False),))
        a = envelope.payload.get("attributes", {})
        if not isinstance(a, Mapping) or a.get("source_type") != "gps" or a.get("tracking_type") == "connection":
            raise ValueError("GPS requires a position tracker, not a connection or a label-only tracker")
        updated = _state_time(envelope.payload, "last_updated", envelope.observed_at)
        require_aware(updated, "GPS state update")
        attribute = self._definition.options.get("timestamp_attribute")
        value = a.get(attribute) if attribute else updated
        observed = value if isinstance(value, datetime) else datetime.fromisoformat(value) if isinstance(value, str) else None
        if observed is None:
            raise ValueError("GPS provider timestamp must be an explicit timezone-aware ISO timestamp")
        require_aware(observed, "GPS measurement")
        if observed > updated or updated > envelope.received_at:
            raise ValueError("GPS clocks are inconsistent or in the future")
        p = GeographicPosition(a.get("latitude"), a.get("longitude"), a.get("gps_accuracy"), observed,
            state, "provider_timestamp" if attribute else "ha_state_update", attribute)
        prior = self._gps_observation
        if prior and (observed <= prior.geographic_position.observed_at or not attribute and (
                p.latitude, p.longitude, p.accuracy_m, p.native_zone) == (
                prior.geographic_position.latitude, prior.geographic_position.longitude,
                prior.geographic_position.accuracy_m, prior.geographic_position.native_zone)):
            return AdapterResult(ignored=True)  # Metadata updates do not renew a position fix.
        identity = IdentityClaim(self._definition.identity, observed, "registered_device_owner", Quality.HIGH) if self._definition.identity else None
        location = SpatialClaim(SpatialLevel.HOME if state.casefold() == "home" else SpatialLevel.UNKNOWN,
            observed, method="gps_device_home" if state.casefold() == "home" else "gps_device_position", quality=Quality.LOW)
        item = self._observation(replace(envelope, observed_at=observed), kind=TargetKind.DEVICE,
            identity=identity, location=location, count=None, active=True)
        item = replace(item, target_id=self._definition.options["device_id"], geographic_position=p,
            source_diagnostics={"accuracy_unspecified":p.accuracy_m == 0, "provider_clock":bool(attribute)},
            revisions={**item.revisions, **{dimension:RevisionStamp(int(observed.timestamp()*1_000_000), observed)
                for dimension in (RevisionDimension.EVENT_TIME, RevisionDimension.DIAGNOSTICS)}})
        self._gps_observation = item
        return AdapterResult(observations=(item,), source_availability=(SourceAvailability(self.source_id, True),))

    def restore_wifi_observation(self, observation: Observation | None) -> bool:
        """Seed semantic deduplication only when the saved binding still matches."""
        definition = self._definition
        self._wifi_observation = None
        if observation is None:
            return True
        expected_owner = definition.identity
        if (observation.source.family != "wifi_tracker"
                or observation.observation_id != self.source_id
                or observation.target_kind is not TargetKind.DEVICE
                or observation.target_id != definition.options["device_id"]
                or observation.source.native_id not in self._entities
                or RevisionDimension.LIFECYCLE not in observation.revisions
                or observation.count is not None
                or observation.event_id is not None or observation.image is not None
                or observation.location is not None and (observation.location.level is not SpatialLevel.HOME
                    or observation.location.area is not None or observation.location.floor is not None or observation.location.candidates)
                or (observation.identity.value if observation.identity else None) != expected_owner
                or observation.network_attachment is not None and observation.network_attachment_attribute != definition.options.get("ap_attribute")
                or observation.network_attachment_area != definition.options.get("ap_area_map", {}).get(observation.network_attachment)):
            return False
        self._wifi_observation = observation
        return True

    def _wifi_tracker(self, envelope: AdapterEnvelope, state: str) -> AdapterResult:
        """Store endpoint connection and AP attachment, never a body's room."""
        updated = _state_time(envelope.payload, "last_updated", envelope.observed_at)
        changed = _state_time(envelope.payload, "last_changed", envelope.observed_at)
        for value in (updated, changed):
            require_aware(value, "Wi-Fi state time")
        if changed > updated or updated > envelope.received_at:
            raise ValueError("Wi-Fi state clocks are inconsistent")
        attributes = envelope.payload.get("attributes", {})
        unsupported = isinstance(attributes, Mapping) and (
            attributes.get("tracking_type") == "position"
            or attributes.get("source_type") not in (None, "router"))
        active = state == "home" and not unsupported
        options = self._definition.options
        attachment = attributes.get(options.get("ap_attribute")) if active and isinstance(attributes, Mapping) else None
        if not isinstance(attachment, str) or not attachment.strip() or len(attachment) > 256:
            attachment = None
        mapped_area = options.get("ap_area_map", {}).get(attachment)
        facts = {"connected": active, "tracker_unknown": state in INVALID_STATES and state != "unavailable",
                 "tracker_unavailable": state == "unavailable",
                 "unsupported_tracker": unsupported,
                 "attachment_unmapped": attachment is not None and mapped_area is None}
        status = ObservationStatus.ACTIVE if active else (
            ObservationStatus.ENDED if state in ABSENT_AREA_STATES and not unsupported else ObservationStatus.UNKNOWN)
        prior = self._wifi_observation
        if prior is not None:
            prior_time = prior.revisions[RevisionDimension.LIFECYCLE].observed_at
            if updated <= prior_time or (status, attachment, mapped_area, facts) == (
                    prior.status, prior.network_attachment, prior.network_attachment_area, dict(prior.source_diagnostics)):
                return AdapterResult(ignored=True)
        identity = IdentityClaim(self._definition.identity, changed, "registered_device_owner", Quality.HIGH) if self._definition.identity else None
        location = SpatialClaim(SpatialLevel.HOME, changed, method="wifi_connection", quality=Quality.LOW) if active else None
        observation = self._observation(envelope, kind=TargetKind.DEVICE, identity=identity,
                                        location=location, count=None, active=active)
        stamp = RevisionStamp(int(updated.timestamp() * 1_000_000), updated)
        attachment_time = (prior.network_attachment_observed_at if prior and prior.network_attachment == attachment
                           and prior.status is ObservationStatus.ACTIVE else updated) if attachment else None
        observation = replace(observation, target_id=options["device_id"], status=status,
            detected_at=changed, ended_at=updated if status is ObservationStatus.ENDED else None,
            network_attachment=attachment, network_attachment_area=mapped_area,
            network_attachment_observed_at=attachment_time, source_diagnostics=facts,
            network_attachment_attribute=options.get("ap_attribute") if attachment else None,
            revisions={dimension: stamp for dimension in (
                RevisionDimension.LOCATION, RevisionDimension.IDENTITY, RevisionDimension.LIFECYCLE,
                RevisionDimension.DIAGNOSTICS)})
        self._wifi_observation = observation
        return AdapterResult(observations=(observation,))

    def _device_signal(self, envelope: AdapterEnvelope, state: str) -> AdapterResult:
        options = self._definition.options
        metric = options["metric"]
        attributes = envelope.payload.get("attributes", {})
        unit = attributes.get("unit_of_measurement", "") if isinstance(attributes, Mapping) else ""
        unit = unit if isinstance(unit, str) else ""
        status, value = "valid", None
        if state.casefold() in INVALID_STATES:
            status = "unavailable" if state.casefold() == "unavailable" else "unknown"
        else:
            try:
                value = float(state)
                if not math.isfinite(value) or metric != "rssi" and value < 0:
                    status, value = "invalid_value", None
            except ValueError:
                status = "invalid_value"
            units = {"dBm"} if metric == "rssi" else {"m", "cm", "mm"}
            if status == "valid" and unit not in units:
                status, value = "invalid_unit", None
        observed = _state_time(envelope.payload, "last_updated", envelope.observed_at)
        return AdapterResult(device_signals=(DeviceSignalSample(
            source=SourceRef(self.source_id, "bermuda_signal", native_id=envelope.channel,
                             dependency_group=self._definition.dependency_group or options["receiver_id"],
                             coverage_group=self._definition.coverage_group),
            device_id=options["device_id"], receiver_id=options["receiver_id"], metric=metric,
            observed_at=observed, received_at=envelope.received_at, value=value, unit=unit,
            status=status, identity=self._definition.identity,
            clock_basis="ha_state_update" if "last_updated" in envelope.payload else "envelope",
        ),))

    def _source_health(self, state: str) -> AdapterResult:
        """Translate one infrastructure channel without creating presence."""
        configured_healthy = self._definition.options.get("healthy_states")
        if configured_healthy is not None:
            available = state in {
                str(value).casefold() for value in configured_healthy
            }
        else:
            configured_unhealthy = self._definition.options.get(
                "unhealthy_states", tuple(INVALID_STATES)
            )
            available = state not in {
                str(value).casefold() for value in configured_unhealthy
            }
        return AdapterResult(
            remove_source_ids=() if available else (self.source_id,),
            source_availability=(SourceAvailability(self.source_id, available),),
        )

    def _bermuda(self, envelope: AdapterEnvelope, state: str) -> AdapterResult:
        if state.casefold() in ABSENT_AREA_STATES:
            return AdapterResult(
                remove_source_ids=(self.source_id,),
                source_availability=(SourceAvailability(self.source_id, True),),
            )
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
        return AdapterResult(
            observations=(observation,),
            source_availability=(SourceAvailability(self.source_id, True),),
        )

    def _count(self, envelope: AdapterEnvelope, state: str) -> AdapterResult:
        numeric = float(state)
        if not math.isfinite(numeric) or numeric < 0 or not numeric.is_integer():
            raise ValueError("count must be a finite nonnegative integer")
        value = int(numeric)
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
                stable=not active,
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
        attributes = envelope.payload.get("attributes", {})
        source_entity_id = (
            attributes.get("source") if isinstance(attributes, Mapping) else None
        )
        ignored_source_ids = self._definition.options.get("ignored_source_ids", ())
        ignored_source_prefixes = self._definition.options.get(
            "ignored_source_prefixes", ()
        )
        if isinstance(source_entity_id, str) and (
            source_entity_id in ignored_source_ids
            or any(
                source_entity_id.startswith(prefix)
                for prefix in ignored_source_prefixes
            )
        ):
            return AdapterResult(
                remove_source_ids=(self.source_id,),
                source_availability=(SourceAvailability(self.source_id, True),),
            )
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
        location: SpatialClaim | None,
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
        facts = {}
        if self._definition.adapter in {AdapterType.COUNT, AdapterType.BINARY_PRESENCE}:
            facts["measured_clear"] = count is not None and count.maximum == 0
            revisions[RevisionDimension.DIAGNOSTICS] = RevisionStamp(sequence, envelope.observed_at)
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
            source_diagnostics=facts,
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
