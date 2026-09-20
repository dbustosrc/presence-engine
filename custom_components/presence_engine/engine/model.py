"""Immutable contracts shared by adapters, storage and resolvers."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from types import MappingProxyType
from typing import Mapping


CONTRACT_VERSION = 1


def require_aware(value: datetime, field_name: str) -> datetime:
    """Reject ambiguous wall-clock values at the contract boundary."""
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{field_name} must be timezone-aware")
    return value


class Quality(str, Enum):
    UNKNOWN = "unknown"
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"

    @property
    def rank(self) -> int:
        return {
            Quality.UNKNOWN: 0,
            Quality.LOW: 1,
            Quality.MEDIUM: 2,
            Quality.HIGH: 3,
        }[self]


class TargetKind(str, Enum):
    PERSON = "person"
    DEVICE = "device"
    ANIMAL = "animal"
    UNKNOWN_LIVING = "unknown_living"


class ObservationStatus(str, Enum):
    ACTIVE = "active"
    ENDED = "ended"
    UNKNOWN = "unknown"


class SpatialLevel(str, Enum):
    AREA = "area"
    FLOOR = "floor"
    HOME = "home"
    UNKNOWN = "unknown"


class RevisionDimension(str, Enum):
    EVENT_TIME = "event_time"
    IDENTITY = "identity"
    LOCATION = "location"
    CLASSIFICATION = "classification"
    COUNT = "count"
    LIFECYCLE = "lifecycle"
    IMAGE = "image"


@dataclass(frozen=True, order=True, slots=True)
class RevisionStamp:
    """Monotonic dimension revision with an observation-time tie breaker."""

    sequence: int
    observed_at: datetime

    def __post_init__(self) -> None:
        if self.sequence < 0:
            raise ValueError("revision sequence cannot be negative")
        require_aware(self.observed_at, "revision observed_at")


@dataclass(frozen=True, slots=True)
class SourceRef:
    source_id: str
    family: str
    native_id: str | None = None
    dependency_group: str | None = None
    coverage_group: str | None = None

    def __post_init__(self) -> None:
        if not self.source_id.strip() or not self.family.strip():
            raise ValueError("source_id and family are required")


@dataclass(frozen=True, slots=True)
class SpatialClaim:
    level: SpatialLevel
    observed_at: datetime
    area: str | None = None
    floor: str | None = None
    candidates: tuple[str, ...] = ()
    method: str = "unknown"
    quality: Quality = Quality.UNKNOWN
    geometry_context_id: str | None = None

    def __post_init__(self) -> None:
        require_aware(self.observed_at, "spatial observed_at")
        if self.level is SpatialLevel.AREA and not self.area:
            raise ValueError("area-level claims require area")
        if self.level is SpatialLevel.FLOOR and not self.floor:
            raise ValueError("floor-level claims require floor")
        object.__setattr__(self, "candidates", tuple(dict.fromkeys(self.candidates)))


@dataclass(frozen=True, slots=True)
class IdentityClaim:
    value: str
    observed_at: datetime
    method: str
    quality: Quality
    score: float | None = None

    def __post_init__(self) -> None:
        require_aware(self.observed_at, "identity observed_at")
        if not self.value.strip() or not self.method.strip():
            raise ValueError("identity value and method are required")
        if self.score is not None and not 0 <= self.score <= 1:
            raise ValueError("identity score must be between zero and one")


@dataclass(frozen=True, slots=True)
class CountClaim:
    minimum: int
    maximum: int
    observed_at: datetime
    stable: bool
    quality: Quality = Quality.UNKNOWN

    def __post_init__(self) -> None:
        require_aware(self.observed_at, "count observed_at")
        if self.minimum < 0 or self.maximum < self.minimum:
            raise ValueError("invalid count interval")


@dataclass(frozen=True, slots=True)
class ImageReference:
    reference: str
    observed_at: datetime
    area: str | None = None
    event_id: str | None = None

    def __post_init__(self) -> None:
        require_aware(self.observed_at, "image observed_at")
        if not self.reference.strip():
            raise ValueError("image reference is required")


@dataclass(frozen=True, slots=True)
class Observation:
    """One normalized source observation.

    An identity on a DEVICE is an association with its owner; it is not direct
    proof that the person shares the device location.
    """

    observation_id: str
    source: SourceRef
    received_at: datetime
    detected_at: datetime
    target_kind: TargetKind
    status: ObservationStatus = ObservationStatus.ACTIVE
    target_id: str | None = None
    event_id: str | None = None
    classification: str | None = None
    identity: IdentityClaim | None = None
    location: SpatialClaim | None = None
    count: CountClaim | None = None
    image: ImageReference | None = None
    active_since: datetime | None = None
    ended_at: datetime | None = None
    revisions: Mapping[RevisionDimension, RevisionStamp] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.observation_id.strip():
            raise ValueError("observation_id is required")
        require_aware(self.received_at, "received_at")
        require_aware(self.detected_at, "detected_at")
        if self.active_since is not None:
            require_aware(self.active_since, "active_since")
        if self.ended_at is not None:
            require_aware(self.ended_at, "ended_at")
        if self.status is ObservationStatus.ENDED and self.ended_at is None:
            raise ValueError("ended observations require ended_at")
        if self.count is not None and self.count.maximum == 0 and self.status is ObservationStatus.ACTIVE:
            raise ValueError("an active observation cannot assert a zero maximum")
        object.__setattr__(self, "revisions", MappingProxyType(dict(self.revisions)))

    @property
    def key(self) -> tuple[str, str]:
        return (self.source.source_id, self.observation_id)


@dataclass(frozen=True, slots=True)
class DeviceState:
    device_id: str
    linked_identity: str | None
    location: SpatialClaim | None
    source_ids: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class PresenceHypothesis:
    hypothesis_id: str
    kind: TargetKind
    identity: str | None
    location: SpatialClaim | None
    location_status: str
    certainty: Quality
    source_ids: tuple[str, ...]
    candidate_areas: tuple[str, ...] = ()
    classification: str | None = None
    identity_quality: Quality = Quality.UNKNOWN
    identity_method: str | None = None
    identity_observed_at: datetime | None = None
    identity_score: float | None = None
    identity_source_ids: tuple[str, ...] = ()
    location_source_ids: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if self.identity_observed_at is not None:
            require_aware(self.identity_observed_at, "identity_observed_at")


@dataclass(frozen=True, slots=True)
class PresenceSnapshot:
    contract_version: int
    snapshot_id: str
    revision: int
    evaluated_at: datetime
    presences: tuple[PresenceHypothesis, ...]
    devices: tuple[DeviceState, ...]
    count_minimum: int
    count_maximum: int
    coverage_degraded: bool
    conflicts: tuple[str, ...] = ()
    reasons: tuple[str, ...] = ()
    unavailable_source_ids: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        require_aware(self.evaluated_at, "evaluated_at")
        if self.count_minimum < 0 or self.count_maximum < self.count_minimum:
            raise ValueError("invalid snapshot count interval")


@dataclass(frozen=True, slots=True)
class DetectionResult:
    contract_version: int
    detection_id: str
    revision: int
    status: str
    kind: TargetKind
    identity: str | None
    identity_quality: Quality
    location: SpatialClaim | None
    detected_at: datetime
    recognized_at: datetime | None
    spatial_observed_at: datetime | None
    processed_at: datetime
    evidence_ids: tuple[str, ...]
    reasons: tuple[str, ...] = ()
    classification: str | None = None
    identity_method: str | None = None
    identity_score: float | None = None
    source_ids: tuple[str, ...] = ()
    image: ImageReference | None = None

    def __post_init__(self) -> None:
        require_aware(self.detected_at, "detected_at")
        require_aware(self.processed_at, "processed_at")
        if self.recognized_at is not None:
            require_aware(self.recognized_at, "recognized_at")
        if self.spatial_observed_at is not None:
            require_aware(self.spatial_observed_at, "spatial_observed_at")
        if self.identity_score is not None and not 0 <= self.identity_score <= 1:
            raise ValueError("identity score must be between zero and one")
