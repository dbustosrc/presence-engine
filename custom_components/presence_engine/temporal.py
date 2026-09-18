"""Bounded historical camera context used by spatial adapters."""

from __future__ import annotations

from bisect import bisect_right
from dataclasses import dataclass, replace
from datetime import datetime

from .configuration import CameraDefinition
from .engine import require_aware


@dataclass(frozen=True, slots=True)
class CameraContextPoint:
    """One coherent PTZ/profile context at a known instant."""

    camera_id: str
    observed_at: datetime
    profile: str | None = None
    preset: str | None = None
    motion_state: str | None = None
    moving: bool = False
    telemetry_valid: bool = False
    physical_profile_confirmed: bool = False

    def __post_init__(self) -> None:
        require_aware(self.observed_at, "camera context observed_at")


@dataclass(frozen=True, slots=True)
class _CameraContextEvent:
    observed_at: datetime
    role: str
    state: str


class TemporalCameraRegistry:
    """Keeps enough ordered context to query several states back in time."""

    def __init__(
        self,
        cameras: dict[str, CameraDefinition],
        *,
        max_points_per_camera: int = 512,
    ) -> None:
        if max_points_per_camera < 2:
            raise ValueError("max_points_per_camera must be at least two")
        self._cameras = dict(cameras)
        self._max_points = max_points_per_camera
        self._events: dict[str, list[_CameraContextEvent]] = {
            camera_id: [] for camera_id in cameras
        }

    def update(
        self,
        camera_id: str,
        *,
        role: str,
        state: str,
        observed_at: datetime,
    ) -> CameraContextPoint:
        """Insert an out-of-order-safe field update and return coherent context."""
        require_aware(observed_at, "camera context update observed_at")
        if camera_id not in self._cameras:
            raise KeyError(camera_id)
        normalized = state.casefold()
        if role not in {"profile", "preset", "movement"}:
            raise ValueError(f"unknown camera context role: {role}")
        event = _CameraContextEvent(observed_at, role, normalized)
        self._insert(camera_id, event)
        point = self.at(camera_id, observed_at)
        assert point is not None
        return point

    def at(self, camera_id: str, observed_at: datetime) -> CameraContextPoint | None:
        """Return the last coherent context no later than an observation."""
        require_aware(observed_at, "camera context lookup observed_at")
        events = self._events.get(camera_id, ())
        index = bisect_right([event.observed_at for event in events], observed_at)
        if index == 0:
            return None
        camera = self._cameras[camera_id]
        point = CameraContextPoint(camera_id=camera_id, observed_at=events[0].observed_at)
        for event in events[:index]:
            if event.role == "profile":
                point = replace(
                    point,
                    observed_at=event.observed_at,
                    profile=event.state or None,
                    physical_profile_confirmed=False,
                )
            elif event.role == "preset":
                point = replace(
                    point,
                    observed_at=event.observed_at,
                    preset=event.state or None,
                    physical_profile_confirmed=False,
                )
            else:
                moving = event.state in camera.moving_states
                stable = event.state in camera.stable_states
                point = replace(
                    point,
                    observed_at=event.observed_at,
                    motion_state=event.state,
                    moving=moving,
                    telemetry_valid=moving or stable,
                    physical_profile_confirmed=stable and point.profile is not None,
                )
        return point

    def latest(self, camera_id: str) -> CameraContextPoint | None:
        events = self._events.get(camera_id, ())
        return self.at(camera_id, events[-1].observed_at) if events else None

    def export(self) -> dict[str, list[dict[str, object]]]:
        """Return JSON-compatible bounded state for HA Store."""
        return {
            camera_id: [
                {
                    "observed_at": event.observed_at.isoformat(),
                    "role": event.role,
                    "state": event.state,
                }
                for event in events
            ]
            for camera_id, events in self._events.items()
        }

    def restore(self, raw: dict[str, list[dict[str, object]]]) -> None:
        """Restore only configured cameras and valid points."""
        for camera_id, values in raw.items():
            if camera_id not in self._cameras:
                continue
            restored: list[_CameraContextEvent] = []
            for value in values[-self._max_points :]:
                restored.append(
                    _CameraContextEvent(
                        observed_at=datetime.fromisoformat(str(value["observed_at"])),
                        role=str(value["role"]),
                        state=str(value["state"]),
                    )
                )
            self._events[camera_id] = sorted(restored, key=lambda event: event.observed_at)

    def _insert(self, camera_id: str, event: _CameraContextEvent) -> None:
        events = self._events.setdefault(camera_id, [])
        keys = [(existing.observed_at, existing.role) for existing in events]
        key = (event.observed_at, event.role)
        index = bisect_right(keys, key)
        if index and keys[index - 1] == key:
            events[index - 1] = event
        else:
            events.insert(index, event)
        if len(events) > self._max_points:
            del events[: len(events) - self._max_points]
