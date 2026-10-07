"""Stable JSON projections shared by HA entities, events and actions."""

from __future__ import annotations

from dataclasses import asdict
from typing import Any, Mapping
from urllib.parse import quote

from .engine import DetectionResult, DeviceState, ImageReference, PresenceSnapshot, SpatialClaim
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
        "area_occupancies": [
            {"location": _location(item.location),
             "count": {"minimum": item.count.minimum, "maximum": item.count.maximum},
             "source_ids": list(item.source_ids),
             "support_families": list(item.support_families),
             "support_quality": item.support_quality.value}
            for item in snapshot.area_occupancies
        ],
        "presences": [
            {
                "hypothesis_id": presence.hypothesis_id,
                "kind": presence.kind.value,
                "classification": presence.classification,
                "identity": presence.identity,
                "identity_quality": presence.identity_quality.value,
                "identity_method": presence.identity_method,
                "identity_observed_at": (
                    presence.identity_observed_at.isoformat()
                    if presence.identity_observed_at
                    else None
                ),
                "identity_score": presence.identity_score,
                "identity_source_ids": list(presence.identity_source_ids),
                "location": _location(presence.location),
                "last_location": _location(presence.last_location),
                "location_clear_source_ids": list(presence.location_clear_source_ids),
                "location_source_ids": list(presence.location_source_ids),
                "location_status": presence.location_status,
                "certainty": presence.certainty.value,
                "candidate_areas": list(presence.candidate_areas),
                "source_ids": list(presence.source_ids),
                "last_image": _image(image_map.get(presence.identity or "")),
            }
            for presence in snapshot.presences
        ],
        "devices": [device_payload(device) for device in snapshot.devices],
        "area_activity": activity_payload(snapshot),
    }


def device_payload(device: DeviceState) -> dict[str, Any]:
    """A device fact is not a body location, including an AP attachment."""
    return {
        "device_id": device.device_id,
        "linked_identity": device.linked_identity,
        "location": _location(device.location),
        "source_ids": list(device.source_ids),
        "network_attachment": device.network_attachment,
        "network_attachment_area": device.network_attachment_area,
        "network_attachment_observed_at": (device.network_attachment_observed_at.isoformat()
                                           if device.network_attachment_observed_at else None),
        **({"geographic_position":{**asdict(device.geographic_position),
            "observed_at":device.geographic_position.observed_at.isoformat(),
            "geographic_confidence":device.geographic_position.geographic_quality.value,
            "confidence_basis":"reported_accuracy_at_measurement_time",
            "owner_location_confidence":"not_established_by_gps",
            "coordinate_unit":"degrees", "accuracy_unit":"m", "device_only":True}}
            if device.geographic_position else {}),
    }


def activity_payload(snapshot: PresenceSnapshot) -> list[dict[str, Any]]:
    return [{"area":a.area, "observed_at":a.observed_at.isoformat(), "sources":list(a.source_ids),
        "dependency_groups":list(a.dependency_groups), "derived_sources":list(a.derived_source_ids),
        "unknown_origin_sources":list(a.unknown_origin_source_ids), "confidence":"low",
        "confidence_basis":"context_only", "identity":None, "body_count":None}
        for a in snapshot.area_activity]


def detection_payload(detection: DetectionResult) -> dict[str, Any]:
    return {
        "contract_version": detection.contract_version,
        "detection_id": detection.detection_id,
        "revision": detection.revision,
        "status": detection.status,
        "kind": detection.kind.value,
        "classification": detection.classification,
        "identity": detection.identity,
        "identity_quality": detection.identity_quality.value,
        "identity_method": detection.identity_method,
        "identity_score": detection.identity_score,
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
        "source_ids": list(detection.source_ids),
        "image": image_payload(detection.image),
        "source_diagnostics": {
            source_id: dict(facts) for source_id, facts in detection.source_diagnostics.items()
        },
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
    return {**image_payload(record.image), "detection_id": record.detection_id}


def image_payload(image: ImageReference | None) -> dict[str, Any] | None:
    """Project media references consistently without claiming HTTP availability."""
    if image is None:
        return None
    return {
        "reference": image.reference,
        "url": (
            _browser_image_reference(image.reference)
            if image.snapshot_status != "unavailable" else None
        ),
        "clip_url": (
            _browser_clip_reference(image)
            if image.clip_status not in {"unavailable", "pending"} else None
        ),
        "snapshot_status": image.snapshot_status,
        "clip_status": image.clip_status,
        "observed_at": image.observed_at.isoformat(),
        "area": image.area,
        "event_id": image.event_id,
        "origin_id": image.origin_id,
    }


def _browser_image_reference(reference: str) -> str | None:
    if reference.startswith(("/", "http://", "https://")):
        return reference
    if reference.startswith("frigate:event:"):
        event_id = reference.removeprefix("frigate:event:")
        if event_id:
            return (
                "/api/frigate/notifications/"
                f"{quote(event_id, safe='')}/snapshot.jpg"
            )
    return None


def _browser_clip_reference(image: ImageReference) -> str | None:
    if not image.reference.startswith("frigate:event:") or not image.origin_id:
        return None
    event_id = image.reference.removeprefix("frigate:event:")
    if not event_id:
        return None
    return (
        "/api/frigate/notifications/"
        f"{quote(event_id, safe='')}/{quote(image.origin_id, safe='')}/clip.mp4"
    )
