"""Stable JSON projections shared by HA entities, events and actions."""

from __future__ import annotations

from typing import Any, Mapping

from .engine import DetectionResult, PresenceSnapshot, SpatialClaim
from .runtime import ImageRecord


def snapshot_payload(
    snapshot: PresenceSnapshot,
    images: Mapping[str, ImageRecord] | None = None,
) -> dict[str, Any]:
    image_map = images or {}
    return {
        "contract_version": snapshot.contract_version,
        "snapshot_id": snapshot.snapshot_id,
        "revision": snapshot.revision,
        "evaluated_at": snapshot.evaluated_at.isoformat(),
        "count": {
            "minimum": snapshot.count_minimum,
            "maximum": snapshot.count_maximum,
            "exact": snapshot.count_minimum == snapshot.count_maximum,
        },
        "coverage_degraded": snapshot.coverage_degraded,
        "unavailable_source_ids": list(snapshot.unavailable_source_ids),
        "conflicts": list(snapshot.conflicts),
        "reasons": list(snapshot.reasons),
        "presences": [
            {
                "hypothesis_id": presence.hypothesis_id,
                "kind": presence.kind.value,
                "identity": presence.identity,
                "location": _location(presence.location),
                "location_status": presence.location_status,
                "certainty": presence.certainty.value,
                "candidate_areas": list(presence.candidate_areas),
                "source_ids": list(presence.source_ids),
                "last_image": _image(image_map.get(presence.identity or "")),
            }
            for presence in snapshot.presences
        ],
        "devices": [
            {
                "device_id": device.device_id,
                "linked_identity": device.linked_identity,
                "location": _location(device.location),
                "source_ids": list(device.source_ids),
            }
            for device in snapshot.devices
        ],
    }


def detection_payload(detection: DetectionResult) -> dict[str, Any]:
    return {
        "contract_version": detection.contract_version,
        "detection_id": detection.detection_id,
        "revision": detection.revision,
        "status": detection.status,
        "kind": detection.kind.value,
        "identity": detection.identity,
        "identity_quality": detection.identity_quality.value,
        "location": _location(detection.location),
        "detected_at": detection.detected_at.isoformat(),
        "recognized_at": (
            detection.recognized_at.isoformat() if detection.recognized_at else None
        ),
        "spatial_observed_at": (
            detection.spatial_observed_at.isoformat()
            if detection.spatial_observed_at
            else None
        ),
        "processed_at": detection.processed_at.isoformat(),
        "evidence_ids": list(detection.evidence_ids),
        "reasons": list(detection.reasons),
    }


def _location(location: SpatialClaim | None) -> dict[str, Any] | None:
    if location is None:
        return None
    return {
        "level": location.level.value,
        "area": location.area,
        "floor": location.floor,
        "candidates": list(location.candidates),
        "method": location.method,
        "quality": location.quality.value,
        "observed_at": location.observed_at.isoformat(),
        "geometry_context_id": location.geometry_context_id,
    }


def _image(record: ImageRecord | None) -> dict[str, Any] | None:
    if record is None:
        return None
    return {
        "reference": record.image.reference,
        "observed_at": record.image.observed_at.isoformat(),
        "area": record.image.area,
        "event_id": record.image.event_id,
        "detection_id": record.detection_id,
    }
