"""Bounded body/device co-location and conservative receiver handoffs.

Radio ranges describe a device, not a body. Two opposed, non-overlapping
measurement ranges support a probable handoff, never facial certainty.
Anchors deliberately are not restored: a restart requires new co-location.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import datetime, timedelta
from typing import Mapping, TYPE_CHECKING

from .engine.model import DeviceHandoff, DeviceSignalSample, DeviceState, Observation, ObservationStatus, PresenceSnapshot, Quality, SpatialClaim, SpatialLevel, TargetKind

if TYPE_CHECKING:
    from .configuration import SourceDefinition
    from .radar import RadarSample


@dataclass(frozen=True, slots=True)
class _Anchor:
    identity: str
    device_id: str
    area: str
    observed_at: datetime
    phone_source: str
    body_source: str
    ranges: Mapping[str, tuple[float, float]]
    accepted_at: datetime | None = None
    measurement_channels: tuple[str, ...] = ()
    accepted_area: str | None = None


class DeviceAssociations:
    def __init__(self, definitions: Mapping[str, SourceDefinition], *, lifetime: timedelta,
                 measurement_window: timedelta) -> None:
        self.definitions = definitions
        self.lifetime = lifetime
        self.measurement_window = measurement_window
        self.anchors: dict[tuple[str, str], _Anchor] = {}
        self.handoffs: dict[tuple[str, str], DeviceHandoff] = {}
        self.capture_after: datetime | None = None
        self.room_hints: dict[tuple[str, str], DeviceState] = {}
        self.room_hint_deadline: datetime | None = None

    def room_candidates(self, observations, histories, now) -> tuple[DeviceState, ...]:
        """A device-supported room is possible, never a body or carried phone.

        Any admitted physical presence takes this fallback out of contention.
        Keep the first qualification clock; radio refreshes only maintain validity.
        """
        homes = {o.identity.value for o in observations if o.status is ObservationStatus.ACTIVE
            and o.source.family == "person_home" and o.identity
            and o.identity.quality.rank >= Quality.MEDIUM.rank and o.identity.observed_at <= now
            and o.location and o.location.level is SpatialLevel.HOME and o.received_at <= now}
        phones = [o for o in observations if o.status is ObservationStatus.ACTIVE
            and o.target_kind is TargetKind.DEVICE and o.source.family == "bermuda_area"
            and o.identity and o.identity.value in homes and o.identity.observed_at <= now
            and o.location and o.location.area and o.location.quality.rank >= Quality.MEDIUM.rank
            and o.location.observed_at <= now and o.received_at <= now]
        body = any(o.status is ObservationStatus.ACTIVE
            and o.target_kind in {TargetKind.PERSON, TargetKind.UNKNOWN_LIVING}
            and o.source.family != "person_home" and o.location
            and o.location.level in {SpatialLevel.AREA, SpatialLevel.FLOOR}
            and o.location.quality.rank >= Quality.MEDIUM.rank and o.location.observed_at <= now
            and o.received_at <= now and (o.count is None or o.count.maximum > 0)
            for o in observations)
        areas = {}
        for phone in phones:
            areas.setdefault(phone.identity.value, set()).add(phone.location.area)
        hints, deadlines = {}, []
        start = max(now - self.measurement_window,
            self.capture_after + timedelta(microseconds=1) if self.capture_after else now - self.measurement_window)
        for phone in phones if not body else ():
            if len(areas[phone.identity.value]) != 1:
                continue
            supporting = [sid for sid, d in self.definitions.items()
                if d.area == phone.location.area and d.options["device_id"] == phone.target_id
                and d.options["metric"] == "distance" and d.identity in {None, phone.identity.value}
                and self._range(histories.get(sid, []), now, start, now)]
            if not supporting:
                continue
            key = (phone.identity.value, phone.target_id)
            sources = tuple(sorted((phone.source.source_id, *supporting)))
            prior = self.room_hints.get(key)
            # Source membership is factual; adding a receiver must not renew
            # the person's spatial observation clock.
            observed = prior.location.observed_at if prior and prior.location.area == phone.location.area else now
            hints[key] = DeviceState(phone.target_id, phone.identity.value,
                SpatialClaim(SpatialLevel.AREA, observed, area=phone.location.area,
                    floor=phone.location.floor, method="device_room_candidate", quality=Quality.LOW), sources)
            deadlines.append(max(histories[sid][-2].observed_at + self.measurement_window for sid in supporting))
        self.room_hints = hints
        self.room_hint_deadline = min(deadlines, default=None)
        return tuple(hints.values())

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

    @staticmethod
    def _origin_clear(observations, source, origin, after, now):
        return any(o.source.source_id == source and o.status is ObservationStatus.ENDED
            and o.source.family in {"binary_presence", "mtr_count", "count"}
            and o.source_diagnostics.get("measured_clear") is True and o.location
            and o.location.area == origin and o.location.quality.rank >= Quality.MEDIUM.rank
            and o.received_at <= now and o.location.observed_at <= now
            and o.count and o.count.maximum == 0 and o.count.stable
            and after < o.count.observed_at <= now for o in observations)

    def update(self, observations: tuple[Observation, ...], histories: Mapping[str, list[DeviceSignalSample]],
               now: datetime, *, previous: PresenceSnapshot | None = None,
               positions: tuple[RadarSample, ...] = ()) -> tuple[DeviceHandoff, ...]:
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
                                    and b.location.area != phone_areas[key]
                                    or a.measurement_channels and b.identity.value != a.identity
                                    and b.location.area == a.area for b in bodies)}
        for phone in phones:
            key = (phone.identity.value, phone.target_id)
            definitions = {sid: d for sid, d in self.definitions.items()
                           if d.area and d.options["device_id"] == phone.target_id
                           and d.options["metric"] == "distance"
                           and d.identity in {None, phone.identity.value}}
            body = max((b for b in bodies if b.identity.value == phone.identity.value
                        and b.location.area == phone.location.area),
                       key=lambda b: b.location.observed_at, default=None)
            channels = ()
            body_clock = body.location.observed_at if body else None
            body_source = body.source.source_id if body else None
            if (body is None and previous and previous.count_minimum == previous.count_maximum == 1
                    and not any(b.identity.value == phone.identity.value or b.location.area == phone.location.area
                                for b in bodies)):
                accepted = next((p for p in previous.presences if p.identity == phone.identity.value
                    and p.location and p.location.area == phone.location.area
                    and p.identity_quality.rank >= Quality.MEDIUM.rank
                    and p.location_status == "correlated_movement"), None)
                supported = [s for s in positions if accepted and s.source_id in accepted.location_source_ids
                    and any(o.source.source_id == s.source_id and o.status is ObservationStatus.ACTIVE
                        and o.identity is None and o.source.family in {"binary_presence", "mtr_count", "count"}
                        and o.target_kind in {TargetKind.PERSON, TargetKind.UNKNOWN_LIVING}
                        and o.location and o.location.area == phone.location.area
                        and o.location.quality.rank >= Quality.MEDIUM.rank and o.location.observed_at <= now
                        and o.received_at <= now and o.count and o.count.minimum == o.count.maximum == 1
                        and o.count.stable and o.count.quality.rank >= Quality.MEDIUM.rank
                        and o.count.observed_at <= now for o in observations)]
                if supported:
                    point = max(supported, key=lambda s: (s.observed_at, s.entity_id))
                    body_clock, body_source, channels = point.observed_at, point.source_id, (point.entity_id,)
            if (body_clock is not None and now - body_clock < self.measurement_window
                    and (self.capture_after is None or body_clock > self.capture_after)):
                old = self.anchors.get(key)
                if old is None or body_clock > old.observed_at and (not channels or old.measurement_channels):
                    ranges = {sid: value for sid in definitions
                              if (value := self._range(histories.get(sid, []), now,
                                  max(body_clock - self.measurement_window, self.capture_after)
                                      if channels and self.capture_after else body_clock - self.measurement_window,
                                  body_clock))}
                    if any(definitions[sid].area == phone.location.area for sid in ranges):
                        self.anchors[key] = _Anchor(phone.identity.value, phone.target_id,
                            phone.location.area, body_clock, phone.source.source_id, body_source, ranges,
                            measurement_channels=channels)
        # A completed arrival has its own bounded clock. Expiry of the origin
        # anchor forbids new transfers, not this already supported destination.
        confirmed = {}
        for phone in phones:
            key = (phone.identity.value, phone.target_id)
            prior = self.handoffs.get(key)
            if (prior and prior.accepted_at is not None
                    and prior.origin_clear_source_id is None
                    and prior.accepted_at <= now < prior.accepted_at + self.lifetime
                    and phone.location.area == prior.destination
                    and not any(b.identity.value == prior.identity for b in bodies)
                    and any(d.area == prior.destination and sid in prior.source_ids
                            and self._range(histories.get(sid, []), now, now - self.measurement_window, now)
                            for sid, d in self.definitions.items())):
                confirmed[key] = prior
        for phone in phones:
            key = (phone.identity.value, phone.target_id)
            if key in confirmed:
                continue
            anchor = self.anchors.get(key)
            if anchor is not None and anchor.measurement_channels:
                handoff = self._correlated_handoff(phone, anchor, observations, bodies, histories, now)
                if handoff is not None:
                    confirmed[key] = handoff
                continue
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
                            anchor.observed_at, observed, sources, destination_before is None,
                            anchor.accepted_at if anchor.accepted_area == phone.location.area else None,
                            arrival_after=anchor.accepted_at if anchor.accepted_area != phone.location.area else None)
                        break
                if key in confirmed:
                    break
        self.handoffs = confirmed
        # Conflicting devices of the same owner cannot pick a room by order.
        destinations = {}
        for handoff in confirmed.values():
            destinations.setdefault(handoff.identity, set()).add(handoff.destination)
        return tuple(h for h in confirmed.values() if len(destinations[h.identity]) == 1)

    def _correlated_handoff(self, phone, anchor, observations, bodies, histories, now):
        """A weaker anchor needs its own clear, opposed radio and a current body.

        The provider's old area remains a device fact, not the person's room.
        Multiple supported destinations stay ambiguous; never choose by order.
        """
        if (any(b.identity.value == anchor.identity for b in bodies)
                or not self._origin_clear(observations, anchor.body_source, anchor.area, anchor.observed_at, now)
                or anchor.accepted_at is not None and now >= anchor.accepted_at + self.lifetime):
            return None
        definitions = {sid: d for sid, d in self.definitions.items() if d.area
            and d.options["device_id"] == phone.target_id and d.options["metric"] == "distance"
            and d.identity in {None, phone.identity.value}}
        destinations = {o.location.area for o in observations if o.status is ObservationStatus.ACTIVE
            and o.identity is None and o.target_kind in {TargetKind.PERSON, TargetKind.UNKNOWN_LIVING}
            and o.location and o.location.area and o.location.area != anchor.area
            and o.location.quality.rank >= Quality.MEDIUM.rank and o.received_at <= now
            and timedelta(0) <= now - o.location.observed_at < self.measurement_window
            and o.count and o.count.minimum > 0 and o.count.observed_at <= now
            and (anchor.accepted_at is None or o.location.area == anchor.accepted_area
                 or o.location.observed_at > anchor.accepted_at)}
        candidates = []
        for origin_id, before in anchor.ranges.items():
            if definitions.get(origin_id) is None or definitions[origin_id].area != anchor.area:
                continue
            departed = self._range(histories.get(origin_id, []), now,
                                  anchor.observed_at + timedelta(microseconds=1), now)
            if departed is None or before[1] >= departed[0]:
                continue
            origin_last = histories[origin_id][-1]
            origin_value = origin_last.value * {"m": 1, "cm": .01, "mm": .001}[origin_last.unit]
            for destination_id, destination in definitions.items():
                if (destination.area not in destinations or phone.location.area not in {anchor.area, destination.area}
                        or destination.options["receiver_id"] == definitions[origin_id].options["receiver_id"]
                        or any(b.location.area == destination.area for b in bodies)):
                    continue
                arriving = self._range(histories.get(destination_id, []), now,
                                      anchor.observed_at + timedelta(microseconds=1), now)
                if arriving is None:
                    continue
                samples = histories[destination_id][-2:]
                values = [s.value * {"m": 1, "cm": .01, "mm": .001}[s.unit] for s in samples]
                prior = self.handoffs.get((anchor.identity, anchor.device_id))
                accepted = prior is not None and prior.destination == destination.area and prior.accepted_at is not None
                destination_before = anchor.ranges.get(destination_id)
                if (values[-1] >= origin_value or not accepted and values[0] <= values[1]
                        or destination_before is not None and arriving[1] >= destination_before[0]):
                    continue
                sources = tuple(sorted((anchor.body_source, anchor.phone_source, origin_id, destination_id)))
                observed = max(origin_last.observed_at, samples[-1].observed_at, anchor.observed_at)
                candidates.append(prior if accepted and prior.source_ids == sources else DeviceHandoff(
                    anchor.identity, anchor.device_id, anchor.area, destination.area, anchor.observed_at,
                    observed, sources, True, anchor.accepted_at if anchor.accepted_area == destination.area else None,
                    origin_clear_source_id=anchor.body_source,
                    origin_measurement_channels=anchor.measurement_channels,
                    arrival_after=anchor.accepted_at if anchor.accepted_area != destination.area else None))
        areas = {h.destination for h in candidates}
        return max(candidates, key=lambda h: (h.observed_at, h.source_ids)) if len(areas) == 1 else None

    def accept(self, snapshot: PresenceSnapshot, now: datetime, radar_motion=()) -> None:
        """Latch only a resolved arrival with independent current body support.

        Radio refreshes, receiver/area oscillations and held body callbacks
        cannot renew this deadline or the original identity/spatial clocks.
        """
        for key, handoff in tuple(self.handoffs.items()):
            supported = any(p.identity == handoff.identity and p.location
                and p.location.area == handoff.destination and p.location_status == "device_carried_probable"
                and any(a.location.area == handoff.destination and a.count.minimum > 0
                        and set(a.source_ids) & set(p.location_source_ids) for a in snapshot.area_occupancies)
                for p in snapshot.presences)
            if supported and handoff.accepted_at is None:
                motion = tuple(m for m in radar_motion if m.area == handoff.destination
                    and any(p.identity == handoff.identity and m.source_id in p.location_source_ids
                            for p in snapshot.presences))
                self.handoffs[key] = replace(handoff, accepted_at=now, radar_motion=motion)
                if (anchor := self.anchors.get(key)) is not None and anchor.observed_at == handoff.anchored_at:
                    self.anchors[key] = replace(anchor, accepted_at=now, accepted_area=handoff.destination)
            elif not supported and handoff.accepted_at is not None:
                del self.handoffs[key]

    def next_expiration(self, now: datetime) -> datetime | None:
        deadlines = [a.observed_at + self.lifetime for a in self.anchors.values()]
        deadlines.extend(h.accepted_at + self.lifetime for h in self.handoffs.values() if h.accepted_at is not None)
        if self.room_hint_deadline is not None:
            deadlines.append(self.room_hint_deadline)
        return min((d for d in deadlines if d > now), default=None)
