"""Camera/PTZ geometry resolution independent of camera brands and transports."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from types import MappingProxyType
from typing import Mapping

from .model import Quality, SpatialClaim, SpatialLevel, require_aware


@dataclass(frozen=True, slots=True)
class CameraGeometry:
    floor: str
    zone_to_area: Mapping[str, str]
    profile_to_area: Mapping[str, str]

    def __post_init__(self) -> None:
        if not self.floor.strip():
            raise ValueError("camera floor is required")
        object.__setattr__(self,"zone_to_area",MappingProxyType(dict(self.zone_to_area)))
        object.__setattr__(self,"profile_to_area",MappingProxyType(dict(self.profile_to_area)))

    @property
    def candidate_areas(self) -> tuple[str, ...]:
        return tuple(sorted(set(self.zone_to_area.values()) | set(self.profile_to_area.values())))


@dataclass(frozen=True, slots=True)
class GeometryContext:
    context_id: str
    observed_at: datetime
    current_zones: tuple[str, ...] = ()
    entered_zones: tuple[str, ...] = ()
    profile: str | None = None
    preset: str | None = None
    moving: bool = False
    telemetry_valid: bool = True
    physical_profile_confirmed: bool = False

    def __post_init__(self) -> None:
        require_aware(self.observed_at,"geometry observed_at")
        if not self.context_id.strip():
            raise ValueError("geometry context_id is required")
        object.__setattr__(self,"current_zones",tuple(dict.fromkeys(self.current_zones)))
        object.__setattr__(self,"entered_zones",tuple(dict.fromkeys(self.entered_zones)))


def resolve_camera_location(context: GeometryContext, geometry: CameraGeometry) -> SpatialClaim:
    """Resolve only what the geometry proves at ``context.observed_at``.

    ``entered_zones`` is intentionally ignored for current location.  A stable
    requested preset is also insufficient: profile fallback requires physical
    confirmation supplied by the adapter.
    """
    if context.moving:
        return SpatialClaim(
            level=SpatialLevel.FLOOR,
            floor=geometry.floor,
            candidates=geometry.candidate_areas,
            method="ptz_transition",
            quality=Quality.UNKNOWN,
            observed_at=context.observed_at,
            geometry_context_id=context.context_id,
        )
    if not context.telemetry_valid:
        return SpatialClaim(
            level=SpatialLevel.FLOOR,
            floor=geometry.floor,
            candidates=geometry.candidate_areas,
            method="geometry_unavailable",
            quality=Quality.UNKNOWN,
            observed_at=context.observed_at,
            geometry_context_id=context.context_id,
        )

    mapped=tuple(dict.fromkeys(
        geometry.zone_to_area[zone]
        for zone in context.current_zones
        if zone in geometry.zone_to_area
    ))
    if len(mapped) == 1:
        return SpatialClaim(
            level=SpatialLevel.AREA,
            area=mapped[0],
            floor=geometry.floor,
            candidates=mapped,
            method="frigate_current_zone",
            quality=Quality.HIGH,
            observed_at=context.observed_at,
            geometry_context_id=context.context_id,
        )
    if len(mapped) > 1:
        return SpatialClaim(
            level=SpatialLevel.FLOOR,
            floor=geometry.floor,
            candidates=tuple(sorted(mapped)),
            method="frigate_current_zones_ambiguous",
            quality=Quality.MEDIUM,
            observed_at=context.observed_at,
            geometry_context_id=context.context_id,
        )

    if context.physical_profile_confirmed and context.profile in geometry.profile_to_area:
        area=geometry.profile_to_area[context.profile]
        return SpatialClaim(
            level=SpatialLevel.AREA,
            area=area,
            floor=geometry.floor,
            candidates=(area,),
            method="ptz_profile_fallback",
            quality=Quality.MEDIUM,
            observed_at=context.observed_at,
            geometry_context_id=context.context_id,
        )

    return SpatialClaim(
        level=SpatialLevel.FLOOR,
        floor=geometry.floor,
        candidates=geometry.candidate_areas,
        method="camera_scope_only",
        quality=Quality.LOW,
        observed_at=context.observed_at,
        geometry_context_id=context.context_id,
    )
