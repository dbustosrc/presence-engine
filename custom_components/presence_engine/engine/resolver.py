"""Deterministic current-presence correlation and counting."""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from datetime import datetime, timedelta
from types import MappingProxyType
from typing import Callable, Iterable, Mapping, Protocol

from .model import (
    CONTRACT_VERSION,
    AreaOccupancy,
    CountClaim,
    DeviceState,
    DeviceHandoff,
    RadarMotionSupport,
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
    previous_continuity_window: timedelta = timedelta(seconds=90)
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
    identity_quality: Quality
    identity_method: str
    identity_observed_at: datetime
    identity_score: float | None
    identity_sources: set[str]
    location_sources: set[str]
    sources: set[str]
    direct_person: bool
    from_device: bool
    status: str = "resolved"
    candidate_areas: set[str] = field(default_factory=set)
    device_locations: list[SpatialClaim] = field(default_factory=list)
    last_location: SpatialClaim | None = None
    clear_sources: set[str] = field(default_factory=set)


@dataclass(frozen=True, slots=True)
class _EvidenceGroup:
    key: str
    kind: TargetKind
    classification: str | None
    location: SpatialClaim | None
    minimum: int
    maximum: int
    source_ids: tuple[str, ...]
    target_id: str | None
    dependency_group: str | None
    coverage_group: str | None
    observer_id: str | None = None


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
        device_handoffs: Iterable[DeviceHandoff] = (),
        radar_motion: Iterable[RadarMotionSupport] = (),
    ) -> PresenceSnapshot:
        now = self._clock.now()
        unavailable = tuple(unavailable_sources)
        observations = tuple(observations)
        active = tuple(sorted(
            (item for item in observations if item.status is ObservationStatus.ACTIVE),
            key=lambda item:(item.detected_at,item.source.source_id,item.observation_id),
        ))
        devices=self._resolve_devices(active)
        clears = tuple(item for item in observations if item.status is ObservationStatus.ENDED
            and item.target_kind in {TargetKind.PERSON, TargetKind.UNKNOWN_LIVING}
            and item.source.family in {"binary_presence", "count", "mtr_count"}
            and item.source.source_id not in unavailable and item.received_at <= now
            and item.source_diagnostics.get("measured_clear") is True
            and item.count is not None and item.count.maximum == 0 and item.count.stable
            and item.location is not None and item.location.area
            and item.location.quality.rank >= Quality.MEDIUM.rank
            and item.location.observed_at <= now
            and item.count.observed_at <= now)
        people=self._known_people(active,previous,now,clears,unavailable)
        groups=self._reconcile_area_populations(self._evidence_groups(active,now))
        guarded_groups=self._guard_spatial_inferences(groups,previous,now)
        inferences_guarded=guarded_groups != groups
        groups=guarded_groups
        handoffs = tuple(device_handoffs)
        self._apply_device_handoffs(people, handoffs, groups, clears, active, now,
                                   tuple(radar_motion), unavailable)
        animals=tuple(group for group in groups if group.kind is TargetKind.ANIMAL)
        physical_areas={group.location.area for group in groups
                        if group.kind is not TargetKind.ANIMAL and group.location
                        and group.location.area and group.maximum}
        conflicts: list[str]=[]
        reasons: list[str]=[]
        if any(person.status == "device_carried_probable" for person in people.values()):
            reasons.append("anchored_device_handoff_with_physical_support")
        if any(h.radar_motion and h.identity in people and people[h.identity].status == "device_carried_probable"
               for h in handoffs):
            reasons.append("radar_motion_corroborated_device_handoff")
        if any(person.status == "location_cleared" for person in people.values()):
            reasons.append("previous_location_support_cleared")
        if inferences_guarded:
            reasons.append("older_spatial_inference_kept_at_floor_scope")
        extras: list[PresenceHypothesis]=[]
        extra_min=0
        extra_max=0
        counted_groups=[]
        animal_consumption: dict[str, set[str]]={}
        person_consumption: set[tuple[str, object]] = set()

        for group in groups:
            if group.kind is TargetKind.ANIMAL:
                continue
            group_min=group.minimum
            group_max=group.maximum
            if group.kind in {TargetKind.PERSON,TargetKind.UNKNOWN_LIVING}:
                eligible = {key: person for key, person in people.items()
                            if self._identity_can_cover(person, group, active, person_consumption)}
                if group.kind is TargetKind.UNKNOWN_LIVING and group.location is not None:
                    overlap=next((animal for animal in animals if animal.minimum > 0
                                  and self._possible_trajectory(group.location,animal.location)
                                  and all(animal.key not in animal_consumption.get(source,set())
                                          for source in group.source_ids)),None)
                    if overlap is not None and group_min:
                        group_min=max(0,group_min-1)
                        for source in group.source_ids:
                            animal_consumption.setdefault(source,set()).add(overlap.key)
                        reasons.append("anonymous_count_may_include_animal")
                corroborated=self._device_corroboration_match(eligible,group,physical_areas)
                if corroborated is not None:
                    person_consumption.add((corroborated.identity, self._identity_bucket(group)))
                    applied=self._apply_group_location(corroborated,group,True)
                    group_min=max(0,group_min-1)
                    if applied and self._exact_identity_match(corroborated,group,active):
                        group_max=max(0,group_max-1)
                    elif not applied:
                        reasons.append("older_location_did_not_rewind_person")
                    else:
                        reasons.append("anonymous_body_identity_overlap")
                if corroborated is None:
                    separated=self._separate_device_proxy_from_physical_presence(
                        people,
                        group,
                    )
                    if separated is not None:
                        # A registered device and an anonymous physical presence
                        # in different rooms are two intact observations, but
                        # not proof of either one or two people. Keep the device
                        # location separate and retain the physical presence as
                        # a possible visitor.
                        group_min=0
                        reasons.append("device_separated_from_physical_presence")
                    same_area=[person for person in eligible.values()
                               if self._same_area(person.location,group.location)]
                    if same_area:
                        if group_min >= len(same_area):
                            for person in same_area:
                                person.sources.update(group.source_ids)
                                # Corroborate location, not identity; active evidence
                                # may repeat, but must not rewind the retained path.
                                if (person.status == "continued"
                                        and person.device_locations
                                        and group.location.observed_at >= person.location.observed_at):
                                    self._apply_group_location(person, group, True)
                        consumed=min(len(same_area),group_max)
                        for person in same_area[:consumed]:
                            person_consumption.add((person.identity, self._identity_bucket(group)))
                        group_min=max(0,group_min-consumed)
                        exact=sum(self._exact_identity_match(person,group,active) for person in same_area[:consumed])
                        group_max=max(0,group_max-exact)
                        if exact < consumed:
                            reasons.append("anonymous_body_identity_overlap")
                    elif group.maximum:
                        match,exact=self._movement_match(eligible,group,now)
                        if match is not None:
                            person_consumption.add((match.identity, self._identity_bucket(group)))
                            applied=self._apply_group_location(match,group,exact)
                            group_min=max(0,group_min-1)
                            if exact and applied and self._exact_identity_match(match,group,active):
                                group_max=max(0,group_max-1)
                            else:
                                reasons.append("movement_correlation_kept_visitor_uncertainty")
                        elif (
                            group.location is not None
                            and group.location.area is None
                            and any(
                                self._possibly_same_location(group.location, person.location)
                                for person in people.values()
                            )
                        ):
                            group_min=max(0,group_min-1)
                            reasons.append("ambiguous_count_may_include_known_person")
            extra_min+=group_min
            extra_max+=group_max
            if group_min:
                counted_groups.append((group,group_min))
            for index in range(group_min):
                extras.append(self._anonymous_hypothesis(group,index,"resolved",Quality.MEDIUM))
            if group_max > group_min:
                extras.append(self._anonymous_hypothesis(group,group_min,"possible",Quality.LOW))

        animal_hypotheses,animal_min,animal_max=self._resolve_animals(groups)
        person_hypotheses=tuple(self._to_hypothesis(candidate) for candidate in people.values())
        population_min=self._population_minimum(counted_groups)
        overlapping = self._overlapping_visual_keys(tuple(group for group, _ in counted_groups))
        extras = [replace(item, location_status="possible", certainty=Quality.LOW)
                  if item.hypothesis_id.rsplit(":", 1)[0] in overlapping else item for item in extras]
        presences = tuple(sorted((*person_hypotheses, *animal_hypotheses, *extras),
                         key=lambda item:(item.kind.value,item.identity or "",item.hypothesis_id)))
        if self._overlapping_visual_keys(groups):
            reasons.append("cross_camera_population_overlap")
        if population_min < extra_min:
            reasons.append("cross_area_population_overlap")
        continued=sum(person.status in {"continued", "device_carried_probable"} for person in people.values())
        unlocated=sum(person.status != "continued" and person.location is not None
                      and person.location.level is SpatialLevel.HOME for person in people.values())
        minimum=max(len(person_hypotheses), len(person_hypotheses)-continued-unlocated+population_min)+animal_min
        if unlocated and population_min:
            reasons.append("home_identity_may_overlap_current_body")
        if continued and population_min:
            reasons.append("continued_identity_may_overlap_current_presence")
        maximum=len(person_hypotheses)+animal_max+extra_max
        occupancies=self._area_occupancies(groups, active, people)
        minimum=max(minimum, max((area.count.minimum for area in occupancies), default=0))
        maximum=max(maximum, minimum)
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
            area_occupancies=occupancies,
        )

    def _apply_device_handoffs(self, people: dict[str, _PersonCandidate], handoffs: tuple[DeviceHandoff, ...],
                              groups: tuple[_EvidenceGroup, ...], clears: tuple[Observation, ...],
                              active: tuple[Observation, ...], now: datetime,
                              radar_motion: tuple[RadarMotionSupport, ...], unavailable: tuple[str, ...]) -> None:
        for handoff in handoffs:
            person = people.get(handoff.identity)
            if (person is None or handoff.observed_at > now or handoff.anchored_at > handoff.observed_at
                    or (handoff.accepted_at is not None and not handoff.observed_at <= handoff.accepted_at <= now)
                    or now - (handoff.accepted_at or handoff.anchored_at) >= self._config.previous_continuity_window
                    or any(o.target_kind is TargetKind.PERSON and o.identity and o.identity.value == handoff.identity
                           and o.location and o.location.area for o in active)
                    or handoff.destination not in self._config.area_floors
                    or not any(d.area == handoff.destination for d in person.device_locations)):
                continue
            # Physical evidence or a measured clear is required in addition
            # to radio motion. A held anonymous origin remains possible.
            support = {sid for g in groups if g.kind in {TargetKind.PERSON, TargetKind.UNKNOWN_LIVING}
                       and g.minimum and g.location and g.location.area == handoff.destination
                       and g.location.quality.rank >= Quality.MEDIUM.rank
                       and abs(g.location.observed_at - handoff.observed_at) <= self._config.trajectory_window
                       for sid in g.source_ids}
            motion_sources = {m.source_id for m in (*radar_motion, *handoff.radar_motion)
                if m.area == handoff.destination and handoff.anchored_at < m.observed_at <= now
                and (handoff.accepted_at is not None and m in handoff.radar_motion
                     and m.observed_at <= handoff.accepted_at
                     or abs(m.observed_at - handoff.observed_at) <= self._config.trajectory_window)
                and m.source_id not in unavailable}
            support.update(sid for g in groups if g.kind in {TargetKind.PERSON, TargetKind.UNKNOWN_LIVING}
                and g.minimum == g.maximum == 1 and g.location and g.location.area == handoff.destination
                and g.location.quality.rank >= Quality.MEDIUM.rank and g.location.observed_at <= now
                and g.coverage_group not in unavailable for sid in g.source_ids if sid in motion_sources)
            if not support and any(o.location.area == handoff.destination for o in clears):
                continue  # A measured destination clear cannot be replaced by radio alone.
            support.update(o.source.source_id for o in clears if handoff.accepted_at is None and not handoff.requires_destination_body
                           and o.location.area == handoff.origin
                           and handoff.anchored_at < o.count.observed_at <= handoff.observed_at)
            if not support:
                continue
            if person.location and person.location.area:
                if person.location.observed_at > handoff.observed_at:
                    continue
                person.candidate_areas.add(person.location.area)
            person.candidate_areas.update((handoff.origin, handoff.destination))
            person.location = SpatialClaim(SpatialLevel.AREA, handoff.observed_at,
                area=handoff.destination, floor=self._config.area_floors[handoff.destination],
                method="anchored_device_handoff", quality=Quality.MEDIUM)
            person.location_sources = set(handoff.source_ids) | support
            person.sources = set(person.identity_sources) | person.location_sources
            person.status = "device_carried_probable"
            person.from_device = False
            person.last_location = None
            person.clear_sources.clear()

    def _area_occupancies(
        self, groups: tuple[_EvidenceGroup, ...], observations: tuple[Observation, ...],
        people: dict[str, _PersonCandidate],
    ) -> tuple[AreaOccupancy, ...]:
        """Keep active physical evidence even when correlation consumes its count."""
        by_area: dict[str, list[_EvidenceGroup]] = {}
        for group in groups:
            if group.location and group.location.area and group.maximum:
                by_area.setdefault(group.location.area, []).append(group)
        # Identified bodies are counted separately, but still provide physical
        # area support. Only use the current location's direct sources: a device
        # or a superseded observation must not revive historical occupancy.
        direct=tuple(item for item in observations if item.target_kind is TargetKind.PERSON
                     and item.identity and item.location and item.location.area
                     and item.identity.value in people
                     and people[item.identity.value].status != "continued"
                     and item.source.source_id in people[item.identity.value].location_sources
                     and self._same_area(item.location,people[item.identity.value].location))
        for item in direct:
            by_area.setdefault(item.location.area, [])
        result = []
        for area, items in sorted(by_area.items()):
            sources={source for item in items for source in item.source_ids}
            area_direct=tuple(item for item in direct if item.location.area == area)
            inputs=tuple(item for item in observations if item.identity is None and item.location
                         and item.location.area == area and item.source.source_id in sources)
            inputs += tuple(replace(item,identity=None,target_id=item.target_id or "identity:"+item.identity.value,
                                    classification=item.classification or "person")
                            for item in area_direct if self._observer(item.source) or not any(
                                group.kind is not TargetKind.ANIMAL for group in items))
            items=list(self._reconcile_area_populations(self._evidence_groups(inputs, self._clock.now())))
            if not items:
                continue
            location = max(items, key=lambda item: item.location.observed_at).location
            # ponytail: conservative bounds for overlapping groups; refine
            # independence with the full population-fusion work, not identity guesses.
            minimum = max(max(item.minimum for item in items), self._tracked_minimum(
                [(item, item.minimum) for item in items if item.target_id]),
                self._tracked_minimum([(item,item.minimum) for item in items
                    if item.target_id and item.kind is TargetKind.PERSON]) + self._resolve_animals(tuple(items))[1])
            minimum = max(minimum, max((self._effective_interval(item, self._clock.now()).minimum
                for item in inputs if item.count is not None and item.source.family in
                {"mtr_count", "binary_presence", "count"}), default=0))
            maximum = sum(item.maximum for item in items)
            maximum=max(maximum,minimum)
            sources={source for item in items for source in item.source_ids}
            support=[item for item in observations if item.location and item.location.area == area
                     and (item.source.source_id in sources or item in direct)
                     and abs(location.observed_at-item.location.observed_at) <= self._config.trajectory_window]
            # A phone corroborates only an already associated current person;
            # a stationary device near an animal is not an extra control vote.
            support.extend(item for item in observations if item.target_kind is TargetKind.DEVICE
                           and item.identity and item.location and item.location.area == area
                           and item.identity.value in people
                           and people[item.identity.value].status in {"resolved", "correlated_movement"}
                           and self._same_area(people[item.identity.value].location,item.location)
                           and item.location.observed_at >= people[item.identity.value].location.observed_at
                           and abs(location.observed_at-item.location.observed_at) <= self._config.trajectory_window)
            independent={}
            for item in sorted(support,key=lambda item:(-item.location.quality.rank,item.source.family)):
                if item.location.quality.rank >= Quality.MEDIUM.rank:
                    family=self._support_family(item.source.family)
                    independent.setdefault(item.source.dependency_group or family,family)
            families=tuple(sorted(set(independent.values())))
            quality=max((item.location.quality for item in support
                         if item.target_kind is not TargetKind.DEVICE),
                        key=lambda value:value.rank, default=location.quality)
            result.append(AreaOccupancy(
                location=location,
                count=CountClaim(minimum, maximum, location.observed_at,
                                 minimum == maximum, location.quality),
                source_ids=tuple(sorted(sources)),
                support_families=families,
                support_quality=quality,
            ))
        return tuple(result)

    @staticmethod
    def _support_family(family: str) -> str:
        # Derived object/face/count channels are not independent votes.
        if family in {"frigate_event", "frigate_face", "resolved_event"}:
            return "visual"
        if family in {"mtr_count", "binary_presence"}:
            return "physical_presence"
        return family

    def _guard_spatial_inferences(
        self, groups: tuple[_EvidenceGroup, ...], previous: PresenceSnapshot | None, now: datetime,
    ) -> tuple[_EvidenceGroup, ...]:
        """An older weak visual inference is not a new room observation.

        Retain its body and historical image, but only use floor scope while
        a recent, more precise conflicting observation is retained.
        """
        if previous is None:
            return groups
        precise=[p.location for p in previous.presences if p.location and p.location.area
                 and now-p.location.observed_at <= self._config.trajectory_window]
        result=[]
        for group in groups:
            location=group.location
            conflicts=[prior for prior in precise if location and group.target_id
                       and group.kind is not TargetKind.ANIMAL
                       and location.area and location.floor == prior.floor
                       and location.area != prior.area
                       and self._adjacent(location.area, prior.area)
                       and location.observed_at < prior.observed_at
                       and location.quality.rank < prior.quality.rank]
            if conflicts:
                group=replace(group,location=replace(
                    location,level=SpatialLevel.FLOOR,area=None,quality=Quality.UNKNOWN,
                    candidates=tuple(sorted({location.area,*(p.area for p in conflicts)})),
                    method="superseded_spatial_inference",
                ))
            result.append(group)
        return tuple(result)

    def _population_minimum(self, counted_groups: list[tuple[_EvidenceGroup, int]]) -> int:
        """Overlapping scopes or recent adjacent claims may share a population.

        Keep distinct tracked objects as a lower bound and all upper bounds.
        No association here identifies or moves a person.
        """
        pending=list(counted_groups)
        minimum=0
        while pending:
            cluster=[pending.pop()]
            for group,_ in cluster:
                for candidate in pending[:]:
                    other,_=candidate
                    if (group.location and other.location
                            and (self._possibly_same_location(group.location,other.location)
                                 or (group.location.area and other.location.area
                                     and self._adjacent(group.location.area,other.location.area)))
                            and (not group.target_id and not other.target_id
                                 and self._possibly_same_location(group.location, other.location)
                                 # Held aggregate clocks are not proof of distinct
                                 # populations in overlapping room/floor scopes.
                                 or abs(group.location.observed_at-other.location.observed_at)
                                <= self._config.trajectory_window or (group.observer_id and other.observer_id
                                and self._same_area(group.location,other.location)
                                and group.kind is other.kind and group.classification == other.classification))):
                        cluster.append(candidate)
                        pending.remove(candidate)
            # ponytail: conservative connected overlap bounds, not geometric
            # triangulation; refine independence when measured coverage is available.
            source_bounds={source:sum(count for group,count in cluster
                                     if group.observer_id is None and source in group.source_ids)
                           for group,_ in cluster if group.observer_id is None for source in group.source_ids}
            minimum+=max(max(count for _,count in cluster),
                         self._tracked_minimum([(group,count) for group,count in cluster if group.target_id]),
                         max(source_bounds.values(),default=0))
        return minimum

    @staticmethod
    def _observer(source: SourceRef) -> str | None:
        if source.family not in {"frigate_event", "frigate_face", "resolved_event"}:
            return None
        return source.native_id or (source.coverage_group if source.coverage_group
                                   and source.coverage_group.startswith("camera:") else None)

    @staticmethod
    def _identity_bucket(group: _EvidenceGroup) -> object:
        return group.observer_id or group.coverage_group or group.source_ids

    def _identity_can_cover(
        self, person: _PersonCandidate, group: _EvidenceGroup,
        observations: tuple[Observation, ...], consumed: set[tuple[str, object]],
    ) -> bool:
        if (person.identity, self._identity_bucket(group)) in consumed:
            return False
        if group.observer_id and group.target_id:
            known_targets={item.target_id for item in observations if item.identity
                           and item.identity.value == person.identity and item.target_id
                           and self._observer(item.source) == group.observer_id}
            if known_targets and group.target_id not in known_targets:
                return False
        return True

    def _exact_identity_match(self, person: _PersonCandidate, group: _EvidenceGroup,
                              observations: tuple[Observation, ...]) -> bool:
        if person.status == "device_carried_probable":
            # The aggregate that supported this handoff already bounds the
            # selected room's population. Counting it again as a visitor is
            # not extra identity uncertainty. Never consume a distinct track
            # or an aggregate that did not actually support the association.
            return (group.observer_id is None and group.target_id is None
                    and self._same_area(person.location, group.location)
                    and bool(set(group.source_ids) & person.location_sources))
        if group.observer_id is None:
            return True  # Room aggregates may include an already located occupant.
        return group.target_id is not None and any(item.identity and item.identity.value == person.identity
                   and item.target_id == group.target_id
                   and self._observer(item.source) == group.observer_id for item in observations)

    def _visual_clusters(self, groups: tuple[_EvidenceGroup, ...]) -> Iterable[list[_EvidenceGroup]]:
        # ponytail: current room/class bounds, not appearance re-identification.
        # ACTIVE stationary objects may have old frames; age alone is not proof
        # of another body. The runtime owns lifecycle, expiry and availability.
        clusters={}
        for group in groups:
            key=("visual",group.location.area,group.kind,group.classification) if (
                group.observer_id and group.location and group.location.area) else ("independent",group.key)
            clusters.setdefault(key,[]).append(group)
        return clusters.values()

    def _tracked_minimum(self, counted: list[tuple[_EvidenceGroup, int]]) -> int:
        counts={group.key:count for group,count in counted}
        minimum=0
        for cluster in self._visual_clusters(tuple(group for group,_ in counted)):
            observers={}
            for group in cluster:
                observer=group.observer_id or group.key
                observers[observer]=observers.get(observer,0)+counts[group.key]
            minimum+=max(observers.values())
        return minimum

    def _overlapping_visual_keys(self, groups: tuple[_EvidenceGroup, ...]) -> set[str]:
        possible=set()
        for cluster in self._visual_clusters(groups):
            observers={}
            for group in cluster:
                observers[group.observer_id]=observers.get(group.observer_id,0)+group.minimum
            if len(observers) > 1:
                anchor=min(observers,key=lambda observer:(-observers[observer],observer))
                possible.update(group.key for group in cluster if group.observer_id != anchor)
        return possible

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
                network_attachment=item.network_attachment,
                network_attachment_area=item.network_attachment_area,
                network_attachment_observed_at=item.network_attachment_observed_at,
            ))
        return tuple(sorted(result,key=lambda device:device.device_id))

    def _known_people(
        self,
        observations: tuple[Observation, ...],
        previous: PresenceSnapshot | None,
        now: datetime,
        clears: tuple[Observation, ...] = (),
        unavailable: tuple[str, ...] = (),
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
                    identity_quality=item.identity.quality,
                    identity_method=item.identity.method,
                    identity_observed_at=item.identity.observed_at,
                    identity_score=item.identity.score,
                    identity_sources={item.source.source_id},
                    location_sources={item.source.source_id} if item.location else set(),
                    sources={item.source.source_id},
                    direct_person=True,
                    from_device=False,
                )
            else:
                candidate.sources.add(item.source.source_id)
                candidate.identity_sources.add(item.source.source_id)
                if self._location_rank(item.location,True) > self._location_rank(candidate.location,True):
                    candidate.location=item.location
                    candidate.location_sources={item.source.source_id}
                elif item.location == candidate.location and item.location is not None:
                    candidate.location_sources.add(item.source.source_id)
                if (
                    item.identity.quality.rank,
                    item.identity.observed_at,
                ) > (
                    candidate.identity_quality.rank,
                    candidate.identity_observed_at,
                ):
                    candidate.certainty=item.identity.quality
                    candidate.identity_quality=item.identity.quality
                    candidate.identity_method=item.identity.method
                    candidate.identity_observed_at=item.identity.observed_at
                    candidate.identity_score=item.identity.score

        for item in observations:
            if item.target_kind is not TargetKind.DEVICE or item.identity is None:
                continue
            identity=item.identity.value
            if item.source.family == "wifi_tracker":
                # An AP attachment cannot create a body or room association.
                if identity in people:
                    people[identity].sources.add(item.source.source_id)
                continue
            if identity in people:
                candidate=people[identity]
                candidate.sources.add(item.source.source_id)
                if item.location is not None:
                    candidate.device_locations.append(item.location)
                if candidate.location is None or candidate.location.area is None:
                    candidate.from_device=True
                continue
            people[identity]=_PersonCandidate(
                identity=identity,
                location=self._device_home_scope(item),
                certainty=Quality.MEDIUM if item.identity.quality is Quality.HIGH else Quality.LOW,
                identity_quality=Quality.MEDIUM,
                identity_method="registered_device_presence",
                identity_observed_at=item.identity.observed_at,
                identity_score=item.identity.score,
                identity_sources={item.source.source_id},
                location_sources={item.source.source_id},
                sources={item.source.source_id},
                direct_person=False,
                from_device=True,
                status="home_from_device",
                device_locations=[item.location] if item.location is not None else [],
            )

        if previous is not None:
            for prior in previous.presences:
                if prior.kind is not TargetKind.PERSON or not prior.identity:
                    continue
                current=people.get(prior.identity)
                if ((prior.location and prior.location.method == "anchored_device_handoff")
                        or prior.location_status == "device_association_unconfirmed"):
                    if current and current.location and current.location.level is SpatialLevel.HOME:
                        current.status = "device_association_unconfirmed"
                        current.from_device = False
                    continue  # Revalidate the anchor, not ordinary phone/room coincidence.
                if (current is not None and current.location is not None and current.location.level is SpatialLevel.HOME
                        and prior.last_location is not None
                        and now-prior.last_location.observed_at < self._config.previous_continuity_window):
                    current.last_location = prior.last_location
                    current.clear_sources.update(prior.location_clear_source_ids)
                    current.status = "location_cleared"
                if prior.location is None or prior.location.observed_at > now:
                    continue
                if now-prior.location.observed_at >= self._config.previous_continuity_window:
                    continue
                if current is not None:
                    clear_sources = self._cleared_support(prior, observations, clears)
                    if clear_sources and current.location is not None and current.location.level is SpatialLevel.HOME:
                        # Retire the remembered room, not the identity/home
                        # evidence. A phone's new area is not a body transfer.
                        current.candidate_areas.update(prior.candidate_areas)
                        current.candidate_areas.add(prior.location.area)
                        current.sources.update(clear_sources)
                        current.status = "location_cleared"
                        current.last_location = prior.location
                        current.clear_sources.update(clear_sources)
                        continue
                    if (current.location is not None
                            and (current.from_device
                                 # A missing radio area is not a body departure.
                                 # Retain only the original physical support; the
                                 # room clock stays fixed while radio is missing.
                                 or (current.location.level is SpatialLevel.HOME
                                     and not current.device_locations
                                     and prior.location_status in {"correlated_movement", "continued"}
                                     and prior.location.area
                                     and any(item.target_kind in {TargetKind.PERSON, TargetKind.UNKNOWN_LIVING}
                                             and (item.identity is None or item.identity.value == prior.identity)
                                             and item.source.source_id in prior.location_source_ids
                                             and item.source.source_id not in unavailable
                                             and item.source.coverage_group not in unavailable
                                             and item.location and item.location.area == prior.location.area
                                             and item.location.quality.rank >= Quality.MEDIUM.rank
                                             and item.location.observed_at <= now and item.received_at <= now
                                             and (item.count is None or (item.count.minimum > 0
                                                                        and item.count.observed_at <= now))
                                             for item in observations))
                                 or (prior.location.area and current.location.area
                                     and prior.location.quality.rank >= current.location.quality.rank))
                            and (prior.location.observed_at > current.location.observed_at
                                 or (current.location.level is SpatialLevel.HOME and prior.location.area))):
                        current.candidate_areas.update(prior.candidate_areas)
                        if current.location.area:
                            current.candidate_areas.add(current.location.area)
                        current.location=prior.location
                        current.location_sources=set(prior.location_source_ids)
                        current.status="continued"
                        current.from_device=False
                        current.sources.update(prior.source_ids)
                    continue
        return people

    @staticmethod
    def _cleared_support(
        prior: PresenceHypothesis, active: tuple[Observation, ...], clears: tuple[Observation, ...],
    ) -> set[str]:
        """A measured clear can retire only its own previously supported point.

        This is not proof that a whole room/home is empty. Coverage loss,
        ended visual tracks and zeros synthesized from overlapping zones do
        not provide negatives. Current physical support in the room wins.
        """
        if prior.location is None or prior.location.area is None:
            return set()
        if any(item.target_kind in {TargetKind.PERSON, TargetKind.UNKNOWN_LIVING}
               and (item.identity is None or item.identity.value == prior.identity) and item.location
               and item.location.area == prior.location.area
               and (item.count is None or item.count.maximum > 0) for item in active):
            return set()
        return {item.source.source_id for item in clears
                if item.source.source_id in prior.location_source_ids
                and item.location.area == prior.location.area
                and item.count.observed_at > prior.location.observed_at}

    def _device_corroboration_match(
        self,
        people: dict[str, _PersonCandidate],
        group: _EvidenceGroup,
        physical_areas: set[str],
    ) -> _PersonCandidate | None:
        """Use physical evidence to locate one device-backed person.

        The device does not locate its owner. It only helps correlate a
        separate physical observation when both independently agree on the
        room and there is exactly one eligible identity.
        """
        if group.location is None or group.location.area is None or not group.maximum:
            return None
        candidates = [
            person
            for person in people.values()
            if person.status != "device_association_unconfirmed"
            and ((person.from_device and not (person.location and person.location.area))
                or (person.status == "continued" and person.location is not None
                    and person.location.area not in physical_areas and group.minimum > 0))
            and any(
                location.area == group.location.area
                and (person.status != "continued" or abs(
                    location.observed_at - group.location.observed_at
                ) <= self._config.trajectory_window)
                for location in person.device_locations
            )
        ]
        return candidates[0] if len(candidates) == 1 else None

    @staticmethod
    def _separate_device_proxy_from_physical_presence(
        people: dict[str, _PersonCandidate],
        group: _EvidenceGroup,
    ) -> _PersonCandidate | None:
        """Preserve a phone/person split without inventing an identity.

        A device only supports home scope. When a physical source does not
        corroborate its room, neither observation may overwrite the other and
        the anonymous presence must remain possible.
        """
        if group.location is None or group.location.area is None:
            return None
        candidates = [
            person
            for person in people.values()
            if person.from_device
            and person.device_locations
            and not any(
                location.area == group.location.area
                for location in person.device_locations
            )
        ]
        if len(candidates) != 1:
            return None
        person = candidates[0]
        person.status = "device_person_separation_possible"
        return person

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
                classification=representative.classification,
                location=representative.location,
                minimum=minimum,
                maximum=maximum,
                source_ids=tuple(sorted({item.source.source_id for item in items})),
                target_id=representative.target_id,
                dependency_group=representative.source.dependency_group,
                coverage_group=representative.source.coverage_group,
                observer_id=self._observer(representative.source),
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
            specific_minimum = self._tracked_minimum([(group, group.minimum) for group in specific])
            specific_maximum = sum(group.maximum for group in specific)
            residual_minimum = max(0, aggregate_minimum - specific_maximum)
            residual_maximum = max(0, aggregate_maximum - specific_minimum)
            if residual_maximum == 0:
                # Consumption removes a duplicate population, not the independent
                # sensor corroborating the tracked body's area.
                aggregate_sources={source for group in aggregates for source in group.source_ids}
                for index,group in enumerate(passthrough):
                    if group in specific:
                        passthrough[index]=replace(group,source_ids=tuple(sorted(
                            set(group.source_ids) | aggregate_sources)))
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
                    observer_id=None,
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

    def _apply_group_location(self, person: _PersonCandidate, group: _EvidenceGroup, exact: bool) -> bool:
        assert group.location is not None
        if (person.location and person.location.area
                and group.location.observed_at < person.location.observed_at):
            return False
        if person.location and person.location.area:
            person.candidate_areas.add(person.location.area)
        if group.location.area:
            person.candidate_areas.add(group.location.area)
        person.location=group.location
        person.last_location=None
        person.clear_sources.clear()
        person.location_sources=set(group.source_ids)
        person.sources.update(group.source_ids)
        person.status="correlated_movement" if exact else "ambiguous_movement"
        return True

    def _resolve_animals(
        self,
        groups: tuple[_EvidenceGroup, ...],
    ) -> tuple[tuple[PresenceHypothesis, ...],int,int]:
        animal_groups=[group for group in groups if group.kind is TargetKind.ANIMAL]
        if not animal_groups:
            return ((),0,0)
        by_coverage: dict[tuple[str, str | None],list[_EvidenceGroup]]={}
        independent=[]
        visual=[]
        for group in animal_groups:
            if group.observer_id:
                visual.append(group)
            elif group.coverage_group:
                by_coverage.setdefault(
                    (group.coverage_group, group.classification),
                    [],
                ).append(group)
            else:
                independent.append(group)
        hypotheses=[]
        minimum=0
        maximum=0
        minimum+=self._tracked_minimum([(group,group.minimum) for group in visual])
        maximum+=sum(group.maximum for group in visual)
        overlapping=self._overlapping_visual_keys(visual)
        for group in visual:
            for index in range(group.minimum):
                hypotheses.append(self._anonymous_hypothesis(group,index,
                    "possible" if group.key in overlapping else "resolved",
                    Quality.LOW if group.key in overlapping else Quality.MEDIUM))
            if group.maximum > group.minimum:
                hypotheses.append(self._anonymous_hypothesis(group,group.minimum,"possible",Quality.LOW))
        for group in independent:
            minimum+=group.minimum
            maximum+=group.maximum
            for index in range(group.minimum):
                hypotheses.append(self._anonymous_hypothesis(group,index,"resolved",Quality.MEDIUM))
            if group.maximum > group.minimum:
                hypotheses.append(self._anonymous_hypothesis(group,group.minimum,"possible",Quality.LOW))
        for (coverage, classification),items in sorted(
            by_coverage.items(),
            key=lambda item: (item[0][0], item[0][1] or ""),
        ):
            group_min=max(item.minimum for item in items)
            group_max=sum(item.maximum for item in items)
            minimum+=group_min
            maximum+=group_max
            representative=max(items,key=lambda item:item.location.observed_at if item.location else datetime.min.replace(tzinfo=self._clock.now().tzinfo))
            sources=tuple(sorted({source for item in items for source in item.source_ids}))
            combined=replace(
                representative,
                key=f"coverage:{coverage}:{classification or 'animal'}",
                source_ids=sources,
                minimum=group_min,
                maximum=group_max,
            )
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
            classification=group.classification,
            location_source_ids=group.source_ids if group.location else (),
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
            classification="person",
            identity_quality=candidate.identity_quality,
            identity_method=candidate.identity_method,
            identity_observed_at=candidate.identity_observed_at,
            identity_score=candidate.identity_score,
            identity_source_ids=tuple(sorted(candidate.identity_sources)),
            location_source_ids=tuple(sorted(candidate.location_sources)),
            last_location=candidate.last_location,
            location_clear_source_ids=tuple(sorted(candidate.clear_sources)),
        )

    @staticmethod
    def _location_rank(location: SpatialClaim | None, direct: bool) -> tuple[int,int,datetime]:
        if location is None:
            # The timestamp is never consulted after the two negative rank
            # components, so an aware sentinel is unnecessary here.
            return (-1, -1, datetime.min)
        return (1 if direct else 0, location.quality.rank, location.observed_at)

    @staticmethod
    def _device_home_scope(item: Observation) -> SpatialClaim:
        """Represent what a registered endpoint proves about its owner."""
        observed_at = (
            item.location.observed_at
            if item.location is not None
            else item.identity.observed_at
            if item.identity is not None
            else item.detected_at
        )
        return SpatialClaim(
            level=SpatialLevel.HOME,
            method="registered_device_home_scope",
            quality=Quality.LOW,
            observed_at=observed_at,
        )

    @staticmethod
    def _same_area(left: SpatialClaim | None, right: SpatialClaim | None) -> bool:
        return bool(left and right and left.area and left.area == right.area)

    @staticmethod
    def _possibly_same_location(left: SpatialClaim, right: SpatialClaim | None) -> bool:
        if right is None:
            return False
        if left.area and right.area:
            return left.area == right.area
        if not left.floor or left.floor != right.floor:
            return False
        if left.area:
            return not right.candidates or left.area in right.candidates
        if right.area:
            return not left.candidates or right.area in left.candidates
        return not left.candidates or not right.candidates or bool(
            set(left.candidates) & set(right.candidates)
        )

    def _adjacent(self, left: str, right: str) -> bool:
        return right in self._config.adjacency.get(left,frozenset()) or left in self._config.adjacency.get(right,frozenset())

    def _possible_trajectory(self, left: SpatialClaim, right: SpatialClaim | None) -> bool:
        """Possible shared body, never an identity/species assignment."""
        if right is None:
            return False
        if self._possibly_same_location(left,right):
            return True
        return bool(left.area and right.area and left.floor and left.floor == right.floor
                    and min(left.quality.rank,right.quality.rank) >= Quality.MEDIUM.rank
                    and self._adjacent(left.area,right.area)
                    and abs(left.observed_at-right.observed_at) <= self._config.trajectory_window)
