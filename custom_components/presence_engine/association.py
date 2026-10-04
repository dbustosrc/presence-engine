"""Bounded body/device co-location and conservative receiver handoffs.

Radio ranges describe a device, not a body. Two opposed, non-overlapping
measurement ranges support a probable handoff, never facial certainty.
Anchors deliberately are not restored: a restart requires new co-location.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Mapping, TYPE_CHECKING

from .engine.model import DeviceHandoff, DeviceSignalSample, Observation, ObservationStatus, Quality, TargetKind

if TYPE_CHECKING:
    from .configuration import SourceDefinition


@dataclass(frozen=True, slots=True)
class _Anchor:
    identity: str
    device_id: str
    area: str
    observed_at: datetime
    phone_source: str
    body_source: str
    ranges: Mapping[str, tuple[float, float]]


class DeviceAssociations:
    def __init__(self, definitions: Mapping[str, SourceDefinition], *, lifetime: timedelta,
                 measurement_window: timedelta) -> None:
        self.definitions = definitions
        self.lifetime = lifetime
        self.measurement_window = measurement_window
        self.anchors: dict[tuple[str, str], _Anchor] = {}
        self.handoffs: dict[tuple[str, str], DeviceHandoff] = {}
        self.capture_after: datetime | None = None

    def _range(self, history: list[DeviceSignalSample], now: datetime,
               start: datetime, end: datetime) -> tuple[float, float] | None:
        # A missing/invalid sample breaks the range. Attribute-only callbacks
        # have already been removed by the runtime's measurement deduplicator.
        samples = []
        for sample in history:
            if sample.observed_at > end:
                continue
            if sample.status != "valid":
                samples.clear()
            elif start <= sample.observed_at and now - sample.observed_at < self.measurement_window:
                samples.append(sample)
        if len(samples) < 2:
            return None
        values = [s.value * {"m": 1, "cm": .01, "mm": .001}[s.unit] for s in samples[-2:]]
        return min(values), max(values)

    def update(self, observations: tuple[Observation, ...], histories: Mapping[str, list[DeviceSignalSample]],
               now: datetime) -> tuple[DeviceHandoff, ...]:
        phones = [o for o in observations if o.status is ObservationStatus.ACTIVE
                  and o.target_kind is TargetKind.DEVICE and o.source.family == "bermuda_area"
                  and o.identity and o.location and o.location.area and o.location.observed_at <= now]
        bodies = [o for o in observations if o.status is ObservationStatus.ACTIVE
                  and o.target_kind is TargetKind.PERSON and o.identity and o.identity.quality is Quality.HIGH
                  and o.location and o.location.area and o.location.quality.rank >= Quality.MEDIUM.rank
                  and o.location.observed_at <= now and o.identity.observed_at <= now]
        phone_areas = {(o.identity.value, o.target_id): o.location.area for o in phones}
        self.anchors = {key: a for key, a in self.anchors.items()
                        if key in phone_areas and now - a.observed_at < self.lifetime
                        and not any(b.identity.value == a.identity and b.location.observed_at > a.observed_at
                                    and b.location.area != phone_areas[key] for b in bodies)}
        for phone in phones:
            key = (phone.identity.value, phone.target_id)
            definitions = {sid: d for sid, d in self.definitions.items()
                           if d.area and d.options["device_id"] == phone.target_id
                           and d.options["metric"] == "distance"
                           and d.identity in {None, phone.identity.value}}
            body = max((b for b in bodies if b.identity.value == phone.identity.value
                        and b.location.area == phone.location.area),
                       key=lambda b: b.location.observed_at, default=None)
            if (body is not None and now - body.location.observed_at < self.measurement_window
                    and (self.capture_after is None or body.location.observed_at > self.capture_after)):
                old = self.anchors.get(key)
                if old is None or body.location.observed_at > old.observed_at:
                    ranges = {sid: value for sid in definitions
                              if (value := self._range(histories.get(sid, []), now,
                                  body.location.observed_at - self.measurement_window, body.location.observed_at))}
                    if any(definitions[sid].area == body.location.area for sid in ranges):
                        self.anchors[key] = _Anchor(phone.identity.value, phone.target_id,
                            body.location.area, body.location.observed_at, phone.source.source_id, body.source.source_id, ranges)
        confirmed = {}
        for phone in phones:
            key = (phone.identity.value, phone.target_id)
            anchor = self.anchors.get(key)
            if anchor is None or anchor.area == phone.location.area:
                continue
            # Current accepted body evidence is authoritative, irrespective of
            # how long a stationary target has held its last coordinates.
            if any(b.identity.value == anchor.identity and b.location.area != phone.location.area for b in bodies):
                continue
            definitions = {sid: d for sid, d in self.definitions.items()
                           if d.area and d.options["device_id"] == phone.target_id
                           and d.options["metric"] == "distance" and d.identity in {None, phone.identity.value}}
            for origin_id, origin_before in anchor.ranges.items():
                origin = self.definitions[origin_id]
                if origin.area != anchor.area:
                    continue
                for destination_id, destination in definitions.items():
                    destination_before = anchor.ranges.get(destination_id)
                    if (destination.area != phone.location.area
                            or origin.options["receiver_id"] == destination.options["receiver_id"]):
                        continue
                    origin_after = self._range(histories.get(origin_id, []), now, anchor.observed_at + timedelta(microseconds=1), now)
                    destination_after = self._range(histories.get(destination_id, []), now, anchor.observed_at + timedelta(microseconds=1), now)
                    arriving = False
                    if destination_after:
                        latest = histories[destination_id][-2:]
                        values = [s.value * {"m": 1, "cm": .01, "mm": .001}[s.unit] for s in latest]
                        arriving = values[0] > values[1]
                    if (origin_after and destination_after
                            and (destination_before is None and arriving or destination_before is not None
                                 and origin_before[1] < destination_before[0]
                                 and destination_after[1] < destination_before[0])
                            and origin_before[1] < origin_after[0]
                            and destination_after[1] < origin_after[0]):
                        observed = max(histories[origin_id][-1].observed_at, histories[destination_id][-1].observed_at,
                                       phone.location.observed_at)
                        sources = tuple(sorted((anchor.body_source, anchor.phone_source, origin_id, destination_id)))
                        prior = self.handoffs.get(key)
                        confirmed[key] = prior if prior and prior.destination == phone.location.area and prior.source_ids == sources else DeviceHandoff(
                            anchor.identity, anchor.device_id, anchor.area, phone.location.area,
                            anchor.observed_at, observed, sources, destination_before is None)
                        break
                if key in confirmed:
                    break
        self.handoffs = confirmed
        # Conflicting devices of the same owner cannot pick a room by order.
        destinations = {}
        for handoff in confirmed.values():
            destinations.setdefault(handoff.identity, set()).add(handoff.destination)
        return tuple(h for h in confirmed.values() if len(destinations[h.identity]) == 1)

    def next_expiration(self, now: datetime) -> datetime | None:
        deadlines = [a.observed_at + self.lifetime for a in self.anchors.values()]
        return min((d for d in deadlines if d > now), default=None)
