"""Source adapter registry."""

from .base import (
    AdapterEnvelope,
    AdapterFailure,
    AdapterResult,
    CameraAvailability,
    SourceAvailability,
    SourceAdapter,
)
from .entity import CameraAvailabilityAdapter, EntityStateAdapter, PTZContextAdapter
from .frigate import (
    FrigateEventAdapter,
    FrigateFaceAdapter,
    canonical_frigate_camera_id,
)
from .mtr import MTRCountAdapter

__all__ = [
    "AdapterEnvelope",
    "AdapterFailure",
    "AdapterResult",
    "CameraAvailability",
    "CameraAvailabilityAdapter",
    "EntityStateAdapter",
    "FrigateEventAdapter",
    "FrigateFaceAdapter",
    "canonical_frigate_camera_id",
    "MTRCountAdapter",
    "PTZContextAdapter",
    "SourceAvailability",
    "SourceAdapter",
]
