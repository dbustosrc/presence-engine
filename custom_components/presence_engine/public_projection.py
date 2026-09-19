"""Compatibility-oriented projections derived from one canonical snapshot."""

from __future__ import annotations

from collections import defaultdict
from typing import TYPE_CHECKING, Any, Mapping
from urllib.parse import quote

from .engine import PresenceHypothesis, PresenceSnapshot, Quality, SpatialLevel, TargetKind

if TYPE_CHECKING:
    from .runtime import ImageRecord


_QUALITY_RANK = {
    Quality.UNKNOWN: 0,
    Quality.LOW: 1,
    Quality.MEDIUM: 2,
    Quality.HIGH: 3,
}


def public_presence_projection(
    snapshot: PresenceSnapshot,
    images: Mapping[str, ImageRecord] | None = None,
) -> dict[str, Any]:
    """Return one coherent public-state candidate from a snapshot revision."""
    image_map = images or {}
    presences = [
        _presence_payload(presence, image_map.get(presence.identity or ""))
        for presence in snapshot.presences
    ]
    active_areas = _active_areas(snapshot.presences)
    persons = [
        {
            "person": presence.identity,
            "area": _location_name(presence),
            "last_update": _observed_at(presence),
        }
        for presence in snapshot.presences
        if presence.kind is TargetKind.PERSON and presence.identity is not None
    ]
    counts = _classification_counts(snapshot.presences)
    exact = snapshot.count_minimum == snapshot.count_maximum
    return {
        "state": "on" if snapshot.count_maximum > 0 else "off",
        "contract_version": snapshot.contract_version,
        "snapshot_id": snapshot.snapshot_id,
        "revision": snapshot.revision,
        "generated_at": snapshot.evaluated_at.isoformat(),
        "total": snapshot.count_maximum,
        "active_areas": active_areas,
        "persons": persons,
        "presences": presences,
        "unlocated_presences": [
            item for item in presences if not item["area"] and not item["scope"]
        ],
        "unavailable_sources": list(snapshot.unavailable_source_ids),
        "coverage": {
            "status": "degraded" if snapshot.coverage_degraded else "healthy",
            "unavailable_count": len(snapshot.unavailable_source_ids),
        },
        "count_estimate": {
            "minimum": snapshot.count_minimum,
            "maximum": snapshot.count_maximum,
            "status": "exact" if exact else "interval",
            "basis": "canonical_snapshot",
        },
        "confidence": _aggregate_quality(snapshot.presences),
        "summary": {
            "total": snapshot.count_maximum,
            "minimum": snapshot.count_minimum,
            "maximum": snapshot.count_maximum,
            "persons": counts["person"],
            "dogs": counts["dog"],
            "cats": counts["cat"],
            "animals": counts["animal"],
            "unknown": counts["unknown"],
            "uncertain": not exact,
        },
        "location_conflicts": list(snapshot.conflicts),
        "reasons": list(snapshot.reasons),
    }


def identity_projection(
    snapshot: PresenceSnapshot,
    identity: str,
    images: Mapping[str, ImageRecord] | None = None,
) -> dict[str, Any]:
    """Return tracker/record fields for one identity without inventing absence."""
    presence = next(
        (item for item in snapshot.presences if item.identity == identity),
        None,
    )
    image_record = (images or {}).get(identity)
    image = _image_payload(image_record)
    if presence is None:
        return {
            "state": None,
            "schema_version": 1,
            "contract_version": snapshot.contract_version,
            "snapshot_id": snapshot.snapshot_id,
            "revision": snapshot.revision,
            "identity": identity,
            "classification": "person",
            "confidence": Quality.UNKNOWN.value,
            "location_status": "unknown",
            "candidate_areas": [],
            "last_seen": None,
            "detected_at": None,
            "location_observed_at": None,
            "location_sources": [],
            "location_source": None,
            "location_method": None,
            "location_confidence": Quality.UNKNOWN.value,
            "identity_confidence": Quality.UNKNOWN.value,
            "identity_source": None,
            "identity_sources": [],
            "identity_observed_at": None,
            "identity_score": None,
            "sources": [],
            "entity_picture": _browser_image_reference(image_record),
            "last_image": image,
        }

    location = presence.location
    observed_at = _observed_at(presence)
    return {
        "state": _location_name(presence) or None,
        "schema_version": 1,
        "contract_version": snapshot.contract_version,
        "snapshot_id": snapshot.snapshot_id,
        "revision": snapshot.revision,
        "identity": identity,
        "classification": presence.classification or presence.kind.value,
        "confidence": presence.certainty.value,
        "location_status": presence.location_status,
        "candidate_areas": list(presence.candidate_areas),
        "last_seen": observed_at,
        "detected_at": observed_at,
        "location_observed_at": location.observed_at.isoformat() if location else None,
        "location_sources": list(presence.location_source_ids),
        "location_source": _first(presence.location_source_ids),
        "location_method": location.method if location else None,
        "location_confidence": location.quality.value if location else Quality.UNKNOWN.value,
        "identity_confidence": presence.identity_quality.value,
        "identity_source": presence.identity_method,
        "identity_sources": list(presence.identity_source_ids),
        "identity_observed_at": (
            presence.identity_observed_at.isoformat()
            if presence.identity_observed_at
            else None
        ),
        "identity_score": presence.identity_score,
        "sources": list(presence.source_ids),
        "entity_picture": _browser_image_reference(image_record),
        "last_image": image,
    }


def _presence_payload(
    presence: PresenceHypothesis,
    image_record: ImageRecord | None,
) -> dict[str, Any]:
    location = presence.location
    return {
        "id": presence.identity or presence.hypothesis_id,
        "type": _public_type(presence),
        "identity": presence.identity,
        "area": location.area if location else None,
        "scope": _scope_name(presence),
        "candidate_areas": list(presence.candidate_areas),
        "confidence": presence.certainty.value,
        "location_confidence": location.quality.value if location else Quality.UNKNOWN.value,
        "location_status": presence.location_status,
        "location_sources": list(presence.location_source_ids),
        "location_methods": [location.method] if location else [],
        "identity_confidence": presence.identity_quality.value,
        "identity_score": presence.identity_score,
        "identity_sources": list(presence.identity_source_ids),
        "last_seen": _observed_at(presence),
        "location_observed_at": location.observed_at.isoformat() if location else None,
        "sources": list(presence.source_ids),
        "last_image": _image_payload(image_record),
    }


def _active_areas(presences: tuple[PresenceHypothesis, ...]) -> list[dict[str, Any]]:
    grouped: dict[str, list[PresenceHypothesis]] = defaultdict(list)
    for presence in presences:
        if presence.location and presence.location.area:
            grouped[presence.location.area].append(presence)

    result: list[dict[str, Any]] = []
    for area, items in sorted(grouped.items()):
        confirmed = [item for item in items if item.location_status != "possible"]
        counts = _classification_counts(items)
        sources = sorted({source for item in items for source in item.location_source_ids})
        methods = sorted(
            {
                item.location.method
                for item in items
                if item.location is not None
            }
        )
        observed = max(
            item.location.observed_at
            for item in items
            if item.location is not None
        )
        result.append(
            {
                "area": area,
                "presence_count": len(items),
                "minimum_count": len(confirmed),
                "maximum_count": len(items),
                "count_status": "exact" if len(confirmed) == len(items) else "interval",
                "person_count": counts["person"],
                "dog_count": counts["dog"],
                "cat_count": counts["cat"],
                "animal_count": counts["animal"],
                "unknown_count": counts["unknown"],
                "confidence": _aggregate_quality(items),
                "sources": sources,
                "location_methods": methods,
                "last_observed_at": observed.isoformat(),
            }
        )
    return result


def _classification_counts(
    presences: tuple[PresenceHypothesis, ...] | list[PresenceHypothesis],
) -> dict[str, int]:
    counts = {"person": 0, "dog": 0, "cat": 0, "animal": 0, "unknown": 0}
    for presence in presences:
        public_type = _public_type(presence)
        if public_type in counts:
            counts[public_type] += 1
        elif presence.kind is TargetKind.ANIMAL:
            counts["animal"] += 1
        else:
            counts["unknown"] += 1
    return counts


def _public_type(presence: PresenceHypothesis) -> str:
    classification = (presence.classification or "").casefold()
    if classification in {"person", "dog", "cat"}:
        return classification
    if presence.kind is TargetKind.PERSON:
        return "person"
    if presence.kind is TargetKind.ANIMAL:
        return "animal"
    return "unknown"


def _location_name(presence: PresenceHypothesis) -> str | None:
    location = presence.location
    if location is None:
        return None
    if location.level is SpatialLevel.AREA:
        return location.area
    if location.level is SpatialLevel.FLOOR:
        return location.floor
    if location.level is SpatialLevel.HOME:
        return "home"
    return None


def _scope_name(presence: PresenceHypothesis) -> str | None:
    location = presence.location
    if location is None:
        return None
    if location.level is SpatialLevel.AREA:
        return location.floor
    if location.level is SpatialLevel.FLOOR:
        return location.floor
    if location.level is SpatialLevel.HOME:
        return "home"
    return None


def _observed_at(presence: PresenceHypothesis) -> str | None:
    if presence.location is not None:
        return presence.location.observed_at.isoformat()
    if presence.identity_observed_at is not None:
        return presence.identity_observed_at.isoformat()
    return None


def _aggregate_quality(
    presences: tuple[PresenceHypothesis, ...] | list[PresenceHypothesis],
) -> str:
    if not presences:
        return "none"
    return min(presences, key=lambda item: _QUALITY_RANK[item.certainty]).certainty.value


def _image_payload(record: ImageRecord | None) -> dict[str, Any] | None:
    if record is None:
        return None
    return {
        "reference": record.image.reference,
        "observed_at": record.image.observed_at.isoformat(),
        "area": record.image.area,
        "event_id": record.image.event_id,
        "detection_id": record.detection_id,
    }


def _browser_image_reference(record: ImageRecord | None) -> str | None:
    if record is None:
        return None
    reference = record.image.reference
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


def _first(values: tuple[str, ...]) -> str | None:
    return values[0] if values else None
