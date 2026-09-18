"""Deterministic event/detection projection."""

from __future__ import annotations

from datetime import datetime
from typing import Iterable

from .model import (
    CONTRACT_VERSION,
    DetectionResult,
    Observation,
    ObservationStatus,
    Quality,
    SpatialClaim,
    TargetKind,
    require_aware,
)


def _identity_score(observation: Observation) -> tuple[int, datetime]:
    if observation.identity is None:
        return (-1, observation.received_at)
    return (observation.identity.quality.rank, observation.identity.observed_at)


def _location_score(observation: Observation) -> tuple[int, int, datetime]:
    if observation.location is None:
        return (-1, -1, observation.received_at)
    direct={TargetKind.PERSON:3,TargetKind.ANIMAL:3,TargetKind.UNKNOWN_LIVING:2,TargetKind.DEVICE:1}[
        observation.target_kind
    ]
    return (direct,observation.location.quality.rank,observation.location.observed_at)


def resolve_detection(
    detection_id: str,
    observations: Iterable[Observation],
    *,
    processed_at: datetime,
    revision: int,
) -> DetectionResult:
    """Project one event without rewriting event time with later knowledge."""
    require_aware(processed_at,"processed_at")
    items=tuple(observation for observation in observations if observation.event_id == detection_id)
    if not items:
        raise ValueError(f"no observations for detection {detection_id}")
    detected_at=min(item.detected_at for item in items)
    identity_item=max(items,key=_identity_score)
    identity=identity_item.identity
    location_item=max(items,key=_location_score)
    location: SpatialClaim | None=location_item.location
    kinds=[item.target_kind for item in items if item.target_kind is not TargetKind.DEVICE]
    kind=kinds[0] if kinds else items[0].target_kind
    ended=all(item.status is ObservationStatus.ENDED for item in items)
    status="ended" if ended else "resolved"
    reasons=[]
    if identity is None:
        status="pending" if not ended else "ended_unidentified"
        reasons.append("identity_not_observed")
    if location is None or location.quality is Quality.UNKNOWN:
        status="pending" if not ended else status
        reasons.append("precise_location_not_observed")
    return DetectionResult(
        contract_version=CONTRACT_VERSION,
        detection_id=detection_id,
        revision=revision,
        status=status,
        kind=kind,
        identity=identity.value if identity else None,
        identity_quality=identity.quality if identity else Quality.UNKNOWN,
        location=location,
        detected_at=detected_at,
        recognized_at=identity.observed_at if identity else None,
        spatial_observed_at=location.observed_at if location else None,
        processed_at=processed_at,
        evidence_ids=tuple(sorted({item.observation_id for item in items})),
        reasons=tuple(reasons),
    )
