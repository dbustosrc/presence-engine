"""JSON-safe codecs for bounded runtime recovery."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Mapping

from .engine import (
    CountClaim,
    IdentityClaim,
    ImageReference,
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


def encode_observation(value: Observation) -> dict[str, Any]:
    """Serialize one normalized observation without transport credentials."""
    return {
        "observation_id": value.observation_id,
        "source": {
            "source_id": value.source.source_id,
            "family": value.source.family,
            "native_id": value.source.native_id,
            "dependency_group": value.source.dependency_group,
            "coverage_group": value.source.coverage_group,
        },
        "received_at": value.received_at.isoformat(),
        "detected_at": value.detected_at.isoformat(),
        "target_kind": value.target_kind.value,
        "status": value.status.value,
        "target_id": value.target_id,
        "event_id": value.event_id,
        "classification": value.classification,
        "identity": _encode_identity(value.identity),
        "location": _encode_location(value.location),
        "count": _encode_count(value.count),
        "image": encode_image_reference(value.image),
        "active_since": _time(value.active_since),
        "ended_at": _time(value.ended_at),
        "revisions": {
            dimension.value: {
                "sequence": revision.sequence,
                "observed_at": revision.observed_at.isoformat(),
            }
            for dimension, revision in value.revisions.items()
        },
    }


def decode_observation(raw: Mapping[str, Any]) -> Observation:
    """Deserialize a validated observation from HA Store."""
    source = raw["source"]
    return Observation(
        observation_id=str(raw["observation_id"]),
        source=SourceRef(
            source_id=str(source["source_id"]),
            family=str(source["family"]),
            native_id=_optional_text(source.get("native_id")),
            dependency_group=_optional_text(source.get("dependency_group")),
            coverage_group=_optional_text(source.get("coverage_group")),
        ),
        received_at=_datetime(raw["received_at"]),
        detected_at=_datetime(raw["detected_at"]),
        target_kind=TargetKind(raw["target_kind"]),
        status=ObservationStatus(raw["status"]),
        target_id=_optional_text(raw.get("target_id")),
        event_id=_optional_text(raw.get("event_id")),
        classification=_optional_text(raw.get("classification")),
        identity=_decode_identity(raw.get("identity")),
        location=_decode_location(raw.get("location")),
        count=_decode_count(raw.get("count")),
        image=decode_image_reference(raw.get("image")),
        active_since=_optional_datetime(raw.get("active_since")),
        ended_at=_optional_datetime(raw.get("ended_at")),
        revisions={
            RevisionDimension(dimension): RevisionStamp(
                int(revision["sequence"]), _datetime(revision["observed_at"])
            )
            for dimension, revision in raw.get("revisions", {}).items()
        },
    )


def _encode_identity(value: IdentityClaim | None) -> dict[str, Any] | None:
    if value is None:
        return None
    return {
        "value": value.value,
        "observed_at": value.observed_at.isoformat(),
        "method": value.method,
        "quality": value.quality.value,
        "score": value.score,
    }


def _decode_identity(raw: object) -> IdentityClaim | None:
    if not isinstance(raw, Mapping):
        return None
    return IdentityClaim(
        value=str(raw["value"]),
        observed_at=_datetime(raw["observed_at"]),
        method=str(raw["method"]),
        quality=Quality(raw["quality"]),
        score=float(raw["score"]) if raw.get("score") is not None else None,
    )


def _encode_location(value: SpatialClaim | None) -> dict[str, Any] | None:
    if value is None:
        return None
    return {
        "level": value.level.value,
        "observed_at": value.observed_at.isoformat(),
        "area": value.area,
        "floor": value.floor,
        "candidates": list(value.candidates),
        "method": value.method,
        "quality": value.quality.value,
        "geometry_context_id": value.geometry_context_id,
    }


def _decode_location(raw: object) -> SpatialClaim | None:
    if not isinstance(raw, Mapping):
        return None
    return SpatialClaim(
        level=SpatialLevel(raw["level"]),
        observed_at=_datetime(raw["observed_at"]),
        area=_optional_text(raw.get("area")),
        floor=_optional_text(raw.get("floor")),
        candidates=tuple(str(item) for item in raw.get("candidates", ())),
        method=str(raw.get("method", "unknown")),
        quality=Quality(raw.get("quality", Quality.UNKNOWN.value)),
        geometry_context_id=_optional_text(raw.get("geometry_context_id")),
    )


def _encode_count(value: CountClaim | None) -> dict[str, Any] | None:
    if value is None:
        return None
    return {
        "minimum": value.minimum,
        "maximum": value.maximum,
        "observed_at": value.observed_at.isoformat(),
        "stable": value.stable,
        "quality": value.quality.value,
    }


def _decode_count(raw: object) -> CountClaim | None:
    if not isinstance(raw, Mapping):
        return None
    return CountClaim(
        minimum=int(raw["minimum"]),
        maximum=int(raw["maximum"]),
        observed_at=_datetime(raw["observed_at"]),
        stable=bool(raw["stable"]),
        quality=Quality(raw.get("quality", Quality.UNKNOWN.value)),
    )


def encode_image_reference(value: ImageReference | None) -> dict[str, Any] | None:
    """Serialize an image reference without fetching or embedding image bytes."""
    if value is None:
        return None
    return {
        "reference": value.reference,
        "observed_at": value.observed_at.isoformat(),
        "area": value.area,
        "event_id": value.event_id,
        "origin_id": value.origin_id,
    }


def decode_image_reference(raw: object) -> ImageReference | None:
    """Deserialize an image reference stored independently from an observation."""
    if not isinstance(raw, Mapping):
        return None
    return ImageReference(
        reference=str(raw["reference"]),
        observed_at=_datetime(raw["observed_at"]),
        area=_optional_text(raw.get("area")),
        event_id=_optional_text(raw.get("event_id")),
        origin_id=_optional_text(raw.get("origin_id")),
    )


def _time(value: datetime | None) -> str | None:
    return value.isoformat() if value else None


def _datetime(value: object) -> datetime:
    if not isinstance(value, str):
        raise ValueError("stored datetime must be a string")
    return datetime.fromisoformat(value)


def _optional_datetime(value: object) -> datetime | None:
    return _datetime(value) if value is not None else None


def _optional_text(value: object) -> str | None:
    return value if isinstance(value, str) and value else None
