"""Deterministic current-presence correlation and counting."""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from datetime import datetime, timedelta
from types import MappingProxyType
from typing import Callable, Iterable, Mapping, Protocol

from .model import (
    CONTRACT_VERSION,
    CountClaim,
    DeviceState,
    Observation,
    ObservationStatus,
    PresenceHypothesis,
    PresenceSnapshot,
    Quality,
    SpatialClaim,
    SpatialLevel,
    TargetKind,
    require_aware,
)


class Clock(Protocol):
    def now(self) -> datetime: ...


@dataclass(frozen=True, slots=True)
class FrozenClock:
    value: datetime

    def __post_init__(self) -> None:
        require_aware(self.value,"clock value")

    def now(self) -> datetime:
        return self.value


@dataclass(frozen=True, slots=True)
class PresenceConfig:
    area_floors: Mapping[str, str] = field(default_factory=dict)
    adjacency: Mapping[str, frozenset[str]] = field(default_factory=dict)
    trajectory_window: timedelta = timedelta(seconds=20)
    device_continuity_window: timedelta = timedelta(seconds=180)
    previous_continuity_window: timedelta = timedelta(seconds=180)
    count_stability_window: timedelta = timedelta(seconds=3)

    def __post_init__(self) -> None:
        if any(value.total_seconds() < 0 for value in (
            self.trajectory_window,
            self.device_continuity_window,
            self.previous_continuity_window,
            self.count_stability_window,
        )):
            raise ValueError("resolver windows cannot be negative")
        object.__setattr__(self,"area_floors",MappingProxyType(dict(self.area_floors)))
        object.__setattr__(self,"adjacency",MappingProxyType({
            area:frozenset(neighbours) for area,neighbours in self.adjacency.items()
        }))


@dataclass(slots=True)
class _PersonCandidate:
    identity: str
    location: SpatialClaim | None
    certainty: Quality
    sources: set[str]
    direct_person: bool
    from_device: bool
    status: str = "resolved"
    candidate_areas: set[str] = field(default_factory=set)


@dataclass(frozen=True, slots=True)
class _EvidenceGroup:
    key: str
    kind: TargetKind
    location: SpatialClaim | None
    minimum: int
    maximum: int
    source_ids: tuple[str, ...]
    target_id: str | None
    dependency_group: str | None
    coverage_group: str | None


class PresenceResolver:
    def __init__(self, config: PresenceConfig, clock: Clock) -> None:
        self._config=config
        self._clock=clock

    def resolve(
        self,
        observations: Iterable[Observation],
        *,
        revision: int,
        previous: PresenceSnapshot | None = None,
        unavailable_sources: Iterable[str] = (),
    ) -> PresenceSnapshot:
        now = self._clock.now()
        unavailable = tuple(unavailable_sources)
        active = tuple(sorted(
            (item for item in observations if item.status is ObservationStatus.ACTIVE),
            key=lambda item:(item.detected_at,item.source.source_id,item.observation_id),
        ))
        devices=self._resolve_devices(active)
        people=self._known_people(active,previous,now)
        groups=self._reconcile_area_populations(self._evidence_groups(active,now))
        conflicts: list[str]=[]
        reasons: list[str]=[]
        extras: list[PresenceHypothesis]=[]
        extra_min=0
        extra_max=0

        for group in groups:
            if group.kind is TargetKind.ANIMAL:
                continue
            group_min=group.minimum
            group_max=group.maximum
            if group.kind in {TargetKind.PERSON,TargetKind.UNKNOWN_LIVING}:
                same_area=[person for person in people.values()
                           if self._same_area(person.location,group.location)]
                if same_area:
                    if group_min >= len(same_area):
                        for person in same_area:
                            person.sources.update(group.source_ids)
                    consumed=min(len(same_area),group_max)
                    group_min=max(0,group_min-consumed)
                    group_max=max(0,group_max-consumed)
                elif group.maximum:
                    match,exact=self._movement_match(people,group,now)
                    if match is not None:
                        self._apply_group_location(match,group,exact)
                        group_min=max(0,group_min-1)
                        if exact:
                            group_max=max(0,group_max-1)
                        else:
                            reasons.append("movement_correlation_kept_visitor_uncertainty")
            extra_min+=group_min
            extra_max+=group_max
            for index in range(group_min):
                extras.append(self._anonymous_hypothesis(group,index,"resolved",Quality.MEDIUM))
            if group_max > group_min:
                extras.append(self._anonymous_hypothesis(group,group_min,"possible",Quality.LOW))

        animal_hypotheses,animal_min,animal_max=self._resolve_animals(groups)
        person_hypotheses=tuple(self._to_hypothesis(candidate) for candidate in people.values())
        presences=tuple(sorted(
            (*person_hypotheses,*animal_hypotheses,*extras),
            key=lambda item:(item.kind.value,item.identity or "",item.hypothesis_id),
        ))
        minimum=len(person_hypotheses)+animal_min+extra_min
        maximum=len(person_hypotheses)+animal_max+extra_max
        if unavailable:
            reasons.append("coverage_degraded")
        if maximum > minimum:
            conflicts.append("presence_count_is_an_interval")
        return PresenceSnapshot(
            contract_version=CONTRACT_VERSION,
            snapshot_id=f"snapshot-{revision}",
            revision=revision,
            evaluated_at=now,
            presences=presences,
            devices=devices,
            count_minimum=minimum,
            count_maximum=maximum,
            coverage_degraded=bool(unavailable),
            conflicts=tuple(dict.fromkeys(conflicts)),
            reasons=tuple(dict.fromkeys(reasons)),
            unavailable_source_ids=tuple(sorted(set(unavailable))),
        )

    def _resolve_devices(self, observations: tuple[Observation, ...]) -> tuple[DeviceState, ...]:
        result=[]
        for item in observations:
            if item.target_kind is not TargetKind.DEVICE:
                continue
            result.append(DeviceState(
                device_id=item.target_id or item.observation_id,
                linked_identity=item.identity.value if item.identity else None,
                location=item.location,
                source_ids=(item.source.source_id,),
            ))
        return tuple(sorted(result,key=lambda device:device.device_id))

    def _known_people(
        self,
        observations: tuple[Observation, ...],
        previous: PresenceSnapshot | None,
        now: datetime,
    ) -> dict[str, _PersonCandidate]:
        people: dict[str,_PersonCandidate]={}
        direct=[item for item in observations
                if item.target_kind is TargetKind.PERSON and item.identity is not None]
        for item in direct:
            identity=item.identity.value
            candidate=people.get(identity)
            if candidate is None:
                people[identity]=_PersonCandidate(
                    identity=identity,
                    location=item.location,
                    certainty=item.identity.quality,
                    sources={item.source.source_id},
                    direct_person=True,
                    from_device=False,
                )
            else:
                candidate.sources.add(item.source.source_id)
                if self._location_rank(item.location,True) > self._location_rank(candidate.location,True):
                    candidate.location=item.location
                if item.identity.quality.rank > candidate.certainty.rank:
                    candidate.certainty=item.identity.quality

        for item in observations:
            if item.target_kind is not TargetKind.DEVICE or item.identity is None:
                continue
            identity=item.identity.value
            if identity in people:
                candidate=people[identity]
                candidate.sources.add(item.source.source_id)
                if item.identity.quality.rank > candidate.certainty.rank:
                    candidate.certainty=item.identity.quality
                if self._device_refines_home_scope(candidate.location,item.location):
                    candidate.location=item.location
                    candidate.from_device=True
                    candidate.status="refined_by_device"
                continue
            people[identity]=_PersonCandidate(
                identity=identity,
                location=item.location,
                certainty=Quality.MEDIUM if item.identity.quality is Quality.HIGH else Quality.LOW,
                sources={item.source.source_id},
                direct_person=False,
                from_device=True,
                status="inferred_from_device",
            )

        if previous is not None:
            for prior in previous.presences:
                if prior.kind is not TargetKind.PERSON or not prior.identity:
                    continue
                if prior.location is None:
                    continue
                if now-prior.location.observed_at > self._config.previous_continuity_window:
                    continue
                current=people.get(prior.identity)
                if current is not None:
                    if (current.from_device and current.location is not None
                            and prior.location.observed_at > current.location.observed_at):
                        current.candidate_areas.update(prior.candidate_areas)
                        if current.location.area:
                            current.candidate_areas.add(current.location.area)
                        current.location=prior.location
                        current.status="continued"
                        current.from_device=False
                        current.sources.update(prior.source_ids)
                    continue
                people[prior.identity]=_PersonCandidate(
                    identity=prior.identity,
                    location=prior.location,
                    certainty=Quality.LOW,
                    sources=set(prior.source_ids),
                    direct_person=False,
                    from_device=False,
                    status="continued",
                    candidate_areas=set(prior.candidate_areas),
                )
        return people

    def _evidence_groups(self, observations: tuple[Observation, ...], now: datetime) -> tuple[_EvidenceGroup, ...]:
        grouped: dict[str,list[Observation]]={}
        for item in observations:
            if item.target_kind is TargetKind.DEVICE or item.identity is not None:
                continue
            key=(
                f"target:{item.target_id}" if item.target_id else
                f"dependency:{item.source.dependency_group}" if item.source.dependency_group else
                f"observation:{item.source.source_id}:{item.observation_id}"
            )
            grouped.setdefault(key,[]).append(item)
        results=[]
        for key,items in grouped.items():
            representative=max(items,key=lambda item:(
                item.location.observed_at if item.location else item.detected_at,
                item.received_at,
            ))
            intervals=[self._effective_interval(item,now) for item in items]
            minimum=max(interval.minimum for interval in intervals)
            maximum=max(interval.maximum for interval in intervals)
            results.append(_EvidenceGroup(
                key=key,
                kind=representative.target_kind,
                location=representative.location,
                minimum=minimum,
                maximum=maximum,
                source_ids=tuple(sorted({item.source.source_id for item in items})),
                target_id=representative.target_id,
                dependency_group=representative.source.dependency_group,
                coverage_group=representative.source.coverage_group,
            ))
        return tuple(sorted(results,key=lambda group:group.key))

    def _reconcile_area_populations(
        self,
        groups: tuple[_EvidenceGroup, ...],
    ) -> tuple[_EvidenceGroup, ...]:
        """Apply aggregate room counts as population bounds, not extra people.

        Tracked object IDs remain independent individuals. Anonymous counters,
        radars and other aggregates observing the same room describe the same
        population; their strongest interval is retained and any already
        tracked objects are consumed from that interval.
        """
        passthrough: list[_EvidenceGroup] = []
        by_area: dict[str, list[_EvidenceGroup]] = {}
        for group in groups:
            if (
                group.kind is TargetKind.ANIMAL
                or group.location is None
                or group.location.area is None
            ):
                passthrough.append(group)
                continue
            by_area.setdefault(group.location.area, []).append(group)

        for area, area_groups in sorted(by_area.items()):
            specific = [group for group in area_groups if group.target_id is not None]
            aggregates = [group for group in area_groups if group.target_id is None]
            passthrough.extend(specific)
            if not aggregates:
                continue
            aggregate_minimum = max(group.minimum for group in aggregates)
            aggregate_maximum = max(group.maximum for group in aggregates)
            specific_minimum = sum(group.minimum for group in specific)
            specific_maximum = sum(group.maximum for group in specific)
            residual_minimum = max(0, aggregate_minimum - specific_maximum)
            residual_maximum = max(0, aggregate_maximum - specific_minimum)
            if residual_maximum == 0:
                continue
            representative = max(
                aggregates,
                key=lambda group: (
                    group.location.observed_at if group.location else datetime.min
                ),
            )
            passthrough.append(
                replace(
                    representative,
                    key=f"area-population:{area}",
                    kind=(
                        TargetKind.PERSON
                        if any(group.kind is TargetKind.PERSON for group in aggregates)
                        else TargetKind.UNKNOWN_LIVING
                    ),
                    minimum=residual_minimum,
                    maximum=residual_maximum,
                    source_ids=tuple(
                        sorted(
                            {
                                source_id
                                for group in aggregates
                                for source_id in group.source_ids
                            }
                        )
                    ),
                    target_id=None,
                    dependency_group=f"area-population:{area}",
                )
            )
        return tuple(sorted(passthrough, key=lambda group: group.key))

    def _effective_interval(self, item: Observation, now: datetime) -> CountClaim:
        if item.count is None:
            observed_at=item.location.observed_at if item.location else item.detected_at
            return CountClaim(1,1,observed_at,True,Quality.MEDIUM)
        claim=item.count
        active_since=item.active_since or claim.observed_at
        if claim.maximum > 1 and not claim.stable and now-active_since < self._config.count_stability_window:
            return replace(claim,minimum=min(claim.minimum,1))
        return claim

    def _movement_match(
        self,
        people: dict[str,_PersonCandidate],
        group: _EvidenceGroup,
        now: datetime,
    ) -> tuple[_PersonCandidate | None,bool]:
        if group.location is None:
            return (None,False)
        candidates=[]
        for person in people.values():
            location=person.location
            if location is None:
                continue
            delta=abs(group.location.observed_at-location.observed_at)
            if location.level is SpatialLevel.FLOOR and group.location.area:
                group_floor=self._config.area_floors.get(group.location.area)
                if group_floor and group_floor == location.floor:
                    candidates.append((0,delta,person,person.direct_person))
                    continue
            if location.area and group.location.area and self._adjacent(location.area,group.location.area):
                allowed=(self._config.device_continuity_window if person.from_device
                         else self._config.trajectory_window)
                if delta <= allowed:
                    # Adjacency alone permits a trajectory hypothesis but never
                    # proves that the anonymous observation is the same person;
                    # retain room for a real visitor.
                    candidates.append((1,delta,person,False))
        if not candidates:
            return (None,False)
        _,_,person,exact=min(candidates,key=lambda item:(item[0],item[1],item[2].identity))
        return (person,exact)

    def _apply_group_location(self, person: _PersonCandidate, group: _EvidenceGroup, exact: bool) -> None:
        assert group.location is not None
        if person.location and person.location.area:
            person.candidate_areas.add(person.location.area)
        if group.location.area:
            person.candidate_areas.add(group.location.area)
        person.location=group.location
        person.sources.update(group.source_ids)
        person.status="correlated_movement" if exact else "ambiguous_movement"

    def _resolve_animals(
        self,
        groups: tuple[_EvidenceGroup, ...],
    ) -> tuple[tuple[PresenceHypothesis, ...],int,int]:
        animal_groups=[group for group in groups if group.kind is TargetKind.ANIMAL]
        if not animal_groups:
            return ((),0,0)
        by_coverage: dict[str,list[_EvidenceGroup]]={}
        independent=[]
        for group in animal_groups:
            if group.coverage_group:
                by_coverage.setdefault(group.coverage_group,[]).append(group)
            else:
                independent.append(group)
        hypotheses=[]
        minimum=0
        maximum=0
        for group in independent:
            minimum+=group.minimum
            maximum+=group.maximum
            for index in range(group.minimum):
                hypotheses.append(self._anonymous_hypothesis(group,index,"resolved",Quality.MEDIUM))
            if group.maximum > group.minimum:
                hypotheses.append(self._anonymous_hypothesis(group,group.minimum,"possible",Quality.LOW))
        for coverage,items in sorted(by_coverage.items()):
            group_min=max(item.minimum for item in items)
            group_max=sum(item.maximum for item in items)
            minimum+=group_min
            maximum+=group_max
            representative=max(items,key=lambda item:item.location.observed_at if item.location else datetime.min.replace(tzinfo=self._clock.now().tzinfo))
            sources=tuple(sorted({source for item in items for source in item.source_ids}))
            combined=replace(representative,key=f"coverage:{coverage}",source_ids=sources,minimum=group_min,maximum=group_max)
            for index in range(group_min):
                hypotheses.append(self._anonymous_hypothesis(combined,index,"resolved",Quality.MEDIUM))
            if group_max > group_min:
                hypotheses.append(self._anonymous_hypothesis(combined,group_min,"possible",Quality.LOW))
        return (tuple(hypotheses),minimum,maximum)

    def _anonymous_hypothesis(
        self,
        group: _EvidenceGroup,
        index: int,
        status: str,
        certainty: Quality,
    ) -> PresenceHypothesis:
        return PresenceHypothesis(
            hypothesis_id=f"{group.key}:{index + 1}",
            kind=group.kind,
            identity=None,
            location=group.location,
            location_status=status,
            certainty=certainty,
            source_ids=group.source_ids,
            candidate_areas=group.location.candidates if group.location else (),
        )

    @staticmethod
    def _to_hypothesis(candidate: _PersonCandidate) -> PresenceHypothesis:
        areas=set(candidate.candidate_areas)
        if candidate.location and candidate.location.area:
            areas.add(candidate.location.area)
        return PresenceHypothesis(
            hypothesis_id=f"person:{candidate.identity}",
            kind=TargetKind.PERSON,
            identity=candidate.identity,
            location=candidate.location,
            location_status=candidate.status,
            certainty=candidate.certainty,
            source_ids=tuple(sorted(candidate.sources)),
            candidate_areas=tuple(sorted(areas)),
        )

    @staticmethod
    def _location_rank(location: SpatialClaim | None, direct: bool) -> tuple[int,int,datetime]:
        if location is None:
            # The timestamp is never consulted after the two negative rank
            # components, so an aware sentinel is unnecessary here.
            return (-1, -1, datetime.min)
        return (1 if direct else 0, location.quality.rank, location.observed_at)

    @staticmethod
    def _device_refines_home_scope(
        current: SpatialClaim | None,
        device: SpatialClaim | None,
    ) -> bool:
        """Refine generic home presence without overriding spatial evidence."""
        if device is None:
            return False
        if current is None:
            return True
        return current.level is SpatialLevel.HOME and current.method == "home_scope"

    @staticmethod
    def _same_area(left: SpatialClaim | None, right: SpatialClaim | None) -> bool:
        return bool(left and right and left.area and left.area == right.area)

    def _adjacent(self, left: str, right: str) -> bool:
        return right in self._config.adjacency.get(left,frozenset()) or left in self._config.adjacency.get(right,frozenset())
