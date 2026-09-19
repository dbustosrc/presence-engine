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
from .frigate import FrigateEventAdapter, FrigateFaceAdapter
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
    "MTRCountAdapter",
    "PTZContextAdapter",
    "SourceAvailability",
    "SourceAdapter",
]
