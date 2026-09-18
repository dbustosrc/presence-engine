"""Single-owner runtime connecting adapters to the deterministic core."""

from __future__ import annotations

from collections import OrderedDict
from dataclasses import dataclass, replace
from datetime import datetime, timedelta
from typing import Callable, Iterable, Mapping

from .adapters import (
    AdapterEnvelope,
    AdapterFailure,
    EntityStateAdapter,
    FrigateEventAdapter,
    FrigateFaceAdapter,
    MTRCountAdapter,
    PTZContextAdapter,
    SourceAdapter,
)
from .codec import (
    decode_image_reference,
    decode_observation,
    encode_image_reference,
    encode_observation,
)
from .configuration import AdapterType, EngineConfiguration
from .engine import (
    CONTRACT_VERSION,
    CountClaim,
    DetectionResult,
    EvidenceStore,
    FrozenClock,
    IdentityClaim,
    ImageReference,
    Observation,
    ObservationStatus,
    PresenceConfig,
    PresenceResolver,
    PresenceSnapshot,
    Quality,
    RevisionDimension,
    RevisionStamp,
    SourceRef,
    TargetKind,
    resolve_detection,
)
from .temporal import TemporalCameraRegistry


@dataclass(frozen=True, slots=True)
class ImageRecord:
    identity: str
    image: ImageReference
    detection_id: str


@dataclass(frozen=True, slots=True)
class RuntimeUpdate:
    snapshot: PresenceSnapshot
    detections: tuple[DetectionResult, ...]
    failures: tuple[AdapterFailure, ...]
    changed: bool


class PresenceRuntime:
    """Serialize evidence mutation and expose reusable coherent projections."""

    def __init__(
        self,
        configuration: EngineConfiguration,
        *,
        now: Callable[[], datetime],
        max_records: int = 2_000,
        max_event_envelopes: int = 512,
    ) -> None:
        self.configuration = configuration
        self._now = now
        self._store = EvidenceStore(max_records=max_records)
        self._contexts = TemporalCameraRegistry(dict(configuration.cameras))
        self._adapters = self._build_adapters()
        self._snapshot: PresenceSnapshot | None = None
        self._latest_images: dict[str, ImageRecord] = {}
        self._unavailable_sources: set[str] = set()
        self._failures: dict[str, AdapterFailure] = {}
        self._event_envelopes: OrderedDict[str, AdapterEnvelope] = OrderedDict()
        self._max_event_envelopes = max_event_envelopes
        self._detection_revisions: dict[str, int] = {}
        self._source_expirations = {
            source.source_id: timedelta(seconds=source.expires_after_seconds)
            for source in configuration.sources
            if source.enabled and source.expires_after_seconds is not None
        }
        self._freshness_signature: tuple[tuple[str, str], ...] = ()

    @property
    def snapshot(self) -> PresenceSnapshot:
        if self._snapshot is None:
            self._snapshot = self._resolve_snapshot()
        return self._snapshot

    @property
    def failures(self) -> tuple[AdapterFailure, ...]:
        return tuple(self._failures[key] for key in sorted(self._failures))

    @property
    def latest_images(self) -> Mapping[str, ImageRecord]:
        return dict(self._latest_images)

    def process(self, envelope: AdapterEnvelope) -> RuntimeUpdate:
        """Process one push envelope; isolate each matching adapter failure."""
        self._remember_event_envelope(envelope)
        changed = False
        detection_ids: set[str] = set()
        matched = False
        for adapter in self._adapters:
            if not adapter.accepts(envelope):
                continue
            matched = True
            try:
                result = adapter.parse(envelope)
            except (KeyError, TypeError, ValueError) as err:
                failure = AdapterFailure(adapter.source_id, type(err).__name__, str(err))
                self._failures[adapter.source_id] = failure
                self._unavailable_sources.add(adapter.source_id)
                continue
            self._failures.pop(adapter.source_id, None)
            self._unavailable_sources.discard(adapter.source_id)
            for source_id in result.remove_source_ids:
                changed = bool(self._store.remove_source(source_id)) or changed
                self._unavailable_sources.add(source_id)
            for observation in result.observations:
                update = self._store.upsert(observation)
                changed = update.changed or changed
                if observation.event_id and update.changed:
                    detection_ids.add(observation.event_id)
            changed = result.context_changed or changed

        if any(
            adapter.accepts(envelope)
            and isinstance(adapter, PTZContextAdapter)
            for adapter in self._adapters
        ):
            replay_changed, replay_detection_ids = self._reprocess_event_envelopes()
            changed = replay_changed or changed
            detection_ids.update(replay_detection_ids)

        for detection_id in detection_ids:
            self._detection_revisions[detection_id] = (
                self._detection_revisions.get(detection_id, 0) + 1
            )
        detections = tuple(
            self._resolve_detection(detection_id)
            for detection_id in sorted(detection_ids)
            if self._store.by_event(detection_id)
        )
        for detection in detections:
            self._remember_image(detection)
        if changed or self._snapshot is None:
            self._snapshot = self._resolve_snapshot()
        return RuntimeUpdate(
            snapshot=self.snapshot,
            detections=detections,
            failures=self.failures,
            changed=changed or matched and bool(detections),
        )

    def refresh(self) -> RuntimeUpdate:
        """Re-evaluate time-bounded evidence without polling any source."""
        now = self._now()
        signature = self._current_freshness_signature(now)
        changed = signature != self._freshness_signature
        if changed:
            self._store.advance_revision()
            self._snapshot = self._resolve_snapshot(allow_previous=False)
        return RuntimeUpdate(self.snapshot, (), self.failures, changed)

    def next_expiration(self) -> datetime | None:
        """Return the earliest future expiration of active evidence."""
        now = self._now()
        expirations = [
            observation.received_at + lifetime
            for observation in self._store.active()
            if (lifetime := self._source_expirations.get(observation.source.source_id))
            is not None
            and observation.received_at + lifetime > now
        ]
        return min(expirations, default=None)

    def mark_channel_unavailable(self, source_ids: Iterable[str]) -> RuntimeUpdate:
        """Invalidate configured sources without turning missing coverage into empty home."""
        changed = False
        for source_id in source_ids:
            self._unavailable_sources.add(source_id)
            changed = bool(self._store.remove_source(source_id)) or changed
        self._snapshot = self._resolve_snapshot()
        return RuntimeUpdate(self.snapshot, (), self.failures, changed)

    def detection(self, detection_id: str) -> DetectionResult | None:
        if not self._store.by_event(detection_id):
            return None
        return self._resolve_detection(detection_id)

    def export_state(self) -> dict[str, object]:
        """Return bounded JSON-compatible state for Home Assistant Store."""
        return {
            "contract_version": CONTRACT_VERSION,
            "configured_source_ids": sorted(
                source.source_id for source in self.configuration.sources if source.enabled
            ),
            "observations": [encode_observation(item) for item in self._store.values()],
            "camera_contexts": self._contexts.export(),
            "latest_images": {
                identity: {
                    "detection_id": record.detection_id,
                    "image": encode_image_reference(record.image),
                }
                for identity, record in self._latest_images.items()
            },
            "detection_revisions": dict(self._detection_revisions),
            "unavailable_sources": sorted(self._unavailable_sources),
        }

    def restore_state(self, raw: Mapping[str, object]) -> None:
        """Restore compatible bounded state; one corrupt item does not abort setup."""
        if int(raw.get("contract_version", 0)) != CONTRACT_VERSION:
            return
        configured_source_ids = {
            source.source_id for source in self.configuration.sources if source.enabled
        }
        for item in raw.get("observations", ()):  # type: ignore[union-attr]
            try:
                observation = decode_observation(item)
                if observation.source.source_id not in configured_source_ids:
                    continue
                self._store.upsert(observation)
            except (KeyError, TypeError, ValueError):
                continue
        contexts = raw.get("camera_contexts")
        if isinstance(contexts, dict):
            try:
                self._contexts.restore(contexts)
            except (KeyError, TypeError, ValueError):
                pass
        unavailable = raw.get("unavailable_sources", ())
        if isinstance(unavailable, list):
            self._unavailable_sources.update(
                value
                for value in unavailable
                if isinstance(value, str) and value in configured_source_ids
            )
        images = raw.get("latest_images", {})
        if isinstance(images, Mapping):
            for identity, value in images.items():
                if not isinstance(identity, str) or not isinstance(value, Mapping):
                    continue
                try:
                    image = decode_image_reference(value.get("image"))
                    detection_id = value.get("detection_id")
                    if image is None or not isinstance(detection_id, str):
                        continue
                    self._latest_images[identity] = ImageRecord(
                        identity=identity,
                        image=image,
                        detection_id=detection_id,
                    )
                except (KeyError, TypeError, ValueError):
                    continue
        detection_revisions = raw.get("detection_revisions", {})
        if isinstance(detection_revisions, Mapping):
            for detection_id, revision in detection_revisions.items():
                if isinstance(detection_id, str) and isinstance(revision, int) and revision > 0:
                    self._detection_revisions[detection_id] = revision
        self._snapshot = self._resolve_snapshot()

    def _build_adapters(self) -> tuple[SourceAdapter, ...]:
        adapters: list[SourceAdapter] = []
        for camera in self.configuration.cameras.values():
            if camera.entity_ids:
                adapters.append(PTZContextAdapter(camera, self._contexts))
        for definition in self.configuration.sources:
            if not definition.enabled:
                continue
            if definition.adapter is AdapterType.FRIGATE_EVENTS:
                adapters.append(
                    FrigateEventAdapter(definition, self.configuration.cameras, self._contexts)
                )
            elif definition.adapter is AdapterType.FRIGATE_FACE:
                adapters.append(FrigateFaceAdapter(definition))
            elif definition.adapter is AdapterType.MTR_COUNT:
                adapters.append(MTRCountAdapter(definition))
            elif definition.adapter is not AdapterType.PTZ_CONTEXT:
                adapters.append(EntityStateAdapter(definition))
        return tuple(adapters)

    def _remember_event_envelope(self, envelope: AdapterEnvelope) -> None:
        if envelope.channel_type != "mqtt":
            return
        after = envelope.payload.get("after")
        if not isinstance(after, Mapping):
            return
        event_id = after.get("id")
        if not isinstance(event_id, str) or not event_id:
            return
        self._event_envelopes[event_id] = envelope
        self._event_envelopes.move_to_end(event_id)
        while len(self._event_envelopes) > self._max_event_envelopes:
            self._event_envelopes.popitem(last=False)

    def _reprocess_event_envelopes(self) -> tuple[bool, set[str]]:
        """Re-evaluate cached event geometry after late historical PTZ context."""
        changed = False
        detection_ids: set[str] = set()
        event_adapters = tuple(
            adapter for adapter in self._adapters if isinstance(adapter, FrigateEventAdapter)
        )
        for envelope in self._event_envelopes.values():
            for adapter in event_adapters:
                if not adapter.accepts(envelope):
                    continue
                try:
                    result = adapter.parse(envelope)
                except (KeyError, TypeError, ValueError):
                    continue
                for observation in result.observations:
                    stored = self._store.get(
                        observation.source.source_id,
                        observation.observation_id,
                    )
                    if stored is not None and observation.location is not None:
                        previous = stored.dimension_revisions[RevisionDimension.LOCATION]
                        observation = replace(
                            observation,
                            revisions={
                                RevisionDimension.LOCATION: RevisionStamp(
                                    previous.sequence + 1,
                                    observation.location.observed_at,
                                )
                            },
                        )
                    update = self._store.upsert(observation)
                    changed = update.changed or changed
                    if observation.event_id and update.changed:
                        detection_ids.add(observation.event_id)
        return changed, detection_ids

    def _resolve_snapshot(self, *, allow_previous: bool = True) -> PresenceSnapshot:
        now = self._now()
        self._freshness_signature = self._current_freshness_signature(now)
        resolver = PresenceResolver(
            PresenceConfig(
                area_floors=self.configuration.areas,
                adjacency=self.configuration.adjacency,
            ),
            FrozenClock(now),
        )
        return resolver.resolve(
            self._presence_observations(now),
            revision=self._store.revision,
            previous=self._snapshot if allow_previous else None,
            unavailable_sources=self._unavailable_sources,
        )

    def _presence_observations(self, now: datetime) -> tuple[Observation, ...]:
        current = tuple(
            item for item in self._store.values() if self._is_current(item, now)
        )
        event_ids = sorted(
            {
                item.event_id
                for item in current
                if item.event_id is not None
                and item.source.family == "frigate_event"
                and item.status is ObservationStatus.ACTIVE
            }
        )
        event_observations: list[Observation] = []
        for event_id in event_ids:
            items = tuple(
                item for item in self._store.by_event(event_id) if self._is_current(item, now)
            )
            primary_ended = any(
                item.source.family == "frigate_event"
                and item.status is ObservationStatus.ENDED
                for item in items
            )
            if primary_ended:
                continue
            result = self._resolve_detection(event_id)
            identity = (
                IdentityClaim(
                    result.identity,
                    result.recognized_at or result.detected_at,
                    "resolved_detection",
                    result.identity_quality,
                )
                if result.identity
                else None
            )
            image = max(
                (item.image for item in items if item.image is not None),
                key=lambda value: value.observed_at,
                default=None,
            )
            event_observations.append(
                Observation(
                    observation_id=f"resolved:{event_id}",
                    source=SourceRef(
                        source_id=f"resolved-event:{event_id}",
                        family="resolved_event",
                        dependency_group=f"frigate-target:{event_id}",
                    ),
                    received_at=now,
                    detected_at=result.detected_at,
                    target_kind=result.kind,
                    target_id=event_id,
                    event_id=event_id,
                    identity=identity,
                    location=result.location,
                    count=CountClaim(1, 1, result.detected_at, True, Quality.HIGH),
                    image=image,
                    active_since=result.detected_at,
                )
            )
        non_event = tuple(
            item for item in current
            if item.status is ObservationStatus.ACTIVE and item.event_id is None
        )
        return (*non_event, *event_observations)

    def _is_current(self, observation: Observation, now: datetime) -> bool:
        lifetime = self._source_expirations.get(observation.source.source_id)
        return lifetime is None or now < observation.received_at + lifetime

    def _current_freshness_signature(self, now: datetime) -> tuple[tuple[str, str], ...]:
        return tuple(
            sorted(
                observation.key
                for observation in self._store.active()
                if self._is_current(observation, now)
            )
        )

    def _resolve_detection(self, detection_id: str) -> DetectionResult:
        items = self._store.by_event(detection_id)
        return resolve_detection(
            detection_id,
            items,
            processed_at=self._now(),
            revision=self._detection_revisions.get(detection_id, 1),
        )

    def _remember_image(self, detection: DetectionResult) -> None:
        if not detection.identity:
            return
        images = [
            item.image
            for item in self._store.by_event(detection.detection_id)
            if item.image is not None
        ]
        if not images:
            return
        image = max(images, key=lambda value: value.observed_at)
        current = self._latest_images.get(detection.identity)
        if current is None or image.observed_at > current.image.observed_at:
            self._latest_images[detection.identity] = ImageRecord(
                detection.identity, image, detection.detection_id
            )
