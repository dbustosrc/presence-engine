"""Source adapter registry."""

from .base import AdapterEnvelope, AdapterFailure, AdapterResult, SourceAdapter
from .entity import EntityStateAdapter, PTZContextAdapter
from .frigate import FrigateEventAdapter, FrigateFaceAdapter
from .mtr import MTRCountAdapter

__all__ = [
    "AdapterEnvelope",
    "AdapterFailure",
    "AdapterResult",
    "EntityStateAdapter",
    "FrigateEventAdapter",
    "FrigateFaceAdapter",
    "MTRCountAdapter",
    "PTZContextAdapter",
    "SourceAdapter",
]
