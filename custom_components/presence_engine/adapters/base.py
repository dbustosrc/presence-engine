"""Common adapter contracts."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any, Mapping, Protocol

from ..engine import Observation, require_aware


@dataclass(frozen=True, slots=True)
class AdapterEnvelope:
    """Transport-neutral push message."""

    channel_type: str
    channel: str
    payload: Mapping[str, Any]
    observed_at: datetime
    received_at: datetime

    def __post_init__(self) -> None:
        require_aware(self.observed_at, "envelope observed_at")
        require_aware(self.received_at, "envelope received_at")


@dataclass(frozen=True, slots=True)
class AdapterFailure:
    source_id: str
    error_type: str
    message: str


@dataclass(frozen=True, slots=True)
class CameraAvailability:
    """Coherent availability of one configured camera evidence channel."""

    camera_id: str
    available: bool


@dataclass(frozen=True, slots=True)
class SourceAvailability:
    """Coherent availability of one normalized evidence source."""

    source_id: str
    available: bool


@dataclass(frozen=True, slots=True)
class AdapterResult:
    observations: tuple[Observation, ...] = ()
    remove_source_ids: tuple[str, ...] = ()
    end_observation_ids: tuple[str, ...] = ()
    context_changed: bool = False
    camera_availability: tuple[CameraAvailability, ...] = ()
    source_availability: tuple[SourceAvailability, ...] = ()
    ignored: bool = False


class SourceAdapter(Protocol):
    source_id: str

    def accepts(self, envelope: AdapterEnvelope) -> bool: ...

    def parse(self, envelope: AdapterEnvelope) -> AdapterResult: ...
