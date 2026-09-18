"""Platform-independent presence evidence engine."""

from .detection import resolve_detection
from .geometry import CameraGeometry, GeometryContext, resolve_camera_location
from .model import (
    CONTRACT_VERSION,
    CountClaim,
    DetectionResult,
    DeviceState,
    IdentityClaim,
    ImageReference,
    Observation,
    ObservationStatus,
    PresenceHypothesis,
    PresenceSnapshot,
    Quality,
    RevisionDimension,
    RevisionStamp,
    SourceRef,
    SpatialClaim,
    SpatialLevel,
    TargetKind,
    require_aware,
)
from .resolver import FrozenClock, PresenceConfig, PresenceResolver
from .store import EvidenceStore, StoreUpdate

__all__ = [
    "CONTRACT_VERSION",
    "CameraGeometry",
    "CountClaim",
    "DetectionResult",
    "DeviceState",
    "EvidenceStore",
    "FrozenClock",
    "GeometryContext",
    "IdentityClaim",
    "ImageReference",
    "Observation",
    "ObservationStatus",
    "PresenceConfig",
    "PresenceHypothesis",
    "PresenceResolver",
    "PresenceSnapshot",
    "Quality",
    "RevisionDimension",
    "RevisionStamp",
    "SourceRef",
    "SpatialClaim",
    "SpatialLevel",
    "StoreUpdate",
    "TargetKind",
    "resolve_camera_location",
    "resolve_detection",
    "require_aware",
]
