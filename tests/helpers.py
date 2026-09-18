from __future__ import annotations

from datetime import datetime, timedelta, timezone

from presence_engine.engine import (
    CountClaim,
    IdentityClaim,
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


BASE=datetime(2030,1,1,12,0,0,tzinfo=timezone.utc)


def at(seconds: float=0) -> datetime:
    return BASE+timedelta(seconds=seconds)


def area(name: str, seconds: float=0, *, quality: Quality=Quality.HIGH, method: str="direct") -> SpatialClaim:
    return SpatialClaim(
        level=SpatialLevel.AREA,
        area=name,
        floor="floor_alpha" if name in {"alpha","beta","gamma"} else "floor_beta",
        candidates=(name,),
        method=method,
        quality=quality,
        observed_at=at(seconds),
    )


def floor(seconds: float=0) -> SpatialClaim:
    return SpatialClaim(
        level=SpatialLevel.FLOOR,
        floor="floor_alpha",
        candidates=("alpha","beta","gamma"),
        method="scope_only",
        quality=Quality.LOW,
        observed_at=at(seconds),
    )


def identity(name: str="person_a", seconds: float=0, *, method: str="face") -> IdentityClaim:
    return IdentityClaim(name,at(seconds),method,Quality.HIGH)


def observation(
    observation_id: str,
    *,
    source_id: str | None=None,
    family: str="visual_event",
    kind: TargetKind=TargetKind.PERSON,
    location: SpatialClaim | None=None,
    identity_claim: IdentityClaim | None=None,
    count: CountClaim | None=None,
    detected: float=0,
    received: float=0,
    active_since: float | None=None,
    event_id: str | None=None,
    target_id: str | None=None,
    dependency_group: str | None=None,
    coverage_group: str | None=None,
    status: ObservationStatus=ObservationStatus.ACTIVE,
    ended: float | None=None,
    revisions: dict[RevisionDimension,RevisionStamp] | None=None,
) -> Observation:
    return Observation(
        observation_id=observation_id,
        source=SourceRef(
            source_id=source_id or f"source.{observation_id}",
            family=family,
            dependency_group=dependency_group,
            coverage_group=coverage_group,
        ),
        received_at=at(received),
        detected_at=at(detected),
        target_kind=kind,
        status=status,
        target_id=target_id,
        event_id=event_id,
        identity=identity_claim,
        location=location,
        count=count,
        active_since=at(active_since) if active_since is not None else None,
        ended_at=at(ended) if ended is not None else None,
        revisions=revisions or {},
    )
