"""Home Assistant lifecycle adapter for the platform-neutral runtime."""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from datetime import datetime
import json
import logging
from time import monotonic
from typing import Any

from homeassistant.components import mqtt
from aiohttp import ClientError
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import EVENT_COMPONENT_LOADED
from homeassistant.core import Event, EventStateChangedData, HomeAssistant, State, callback
from homeassistant.helpers import device_registry as dr, entity_registry as er
from homeassistant.helpers.event import async_call_later, async_track_state_change_event
from homeassistant.helpers.storage import Store
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator
from homeassistant.util import dt as dt_util

from .adapters import AdapterEnvelope
from .configuration import EngineConfiguration
from .const import CONF_CONFIGURATION, EVENT_RESULT, STORAGE_KEY_PREFIX, STORAGE_VERSION
from .face_discovery import FaceDiscovery
from .ha_face_catalogue import fetch_face_catalogue
from .discovery import DiscoveryCandidate, discover_candidate
from .engine import DetectionResult, PresenceSnapshot
from .ha_discovery import collect_entity_descriptors
from .projection import detection_payload
from .runtime import PresenceRuntime, RuntimeUpdate


_LOGGER = logging.getLogger(__name__)

DetectionListener = Callable[[DetectionResult], None]
IdentityListener = Callable[[str], None]


class PresenceCoordinator(DataUpdateCoordinator[PresenceSnapshot]):
    """Push-only coordinator; properties never perform I/O."""

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry, snapshot: PresenceSnapshot) -> None:
        super().__init__(
            hass,
            _LOGGER,
            name="Presence Engine",
            config_entry=entry,
            always_update=False,
        )
        self.async_set_updated_data(snapshot)


class HomeAssistantPresenceRuntime:
    """Own subscriptions, persistence and serialized mutation for one entry."""

    def __init__(
        self,
        hass: HomeAssistant,
        entry: ConfigEntry,
        configuration: EngineConfiguration,
        *,
        activated_discovery: tuple[DiscoveryCandidate, ...] = (),
        pending_discovery: tuple[DiscoveryCandidate, ...] = (),
        max_records: int,
        save_delay_seconds: int,
    ) -> None:
        self.hass = hass
        self.entry = entry
        self.engine = PresenceRuntime(
            configuration,
            now=dt_util.utcnow,
            max_records=max_records,
        )
        self.coordinator = PresenceCoordinator(hass, entry, self.engine.snapshot)
        self._store: Store[dict[str, object]] = Store(
            hass,
            STORAGE_VERSION,
            f"{STORAGE_KEY_PREFIX}.{entry.entry_id}",
        )
        self._save_delay_seconds = save_delay_seconds
        self._lock = asyncio.Lock()
        self._unsubscribers: list[Callable[[], None]] = []
        self._detection_listeners: set[DetectionListener] = set()
        self._identity_listeners: set[IdentityListener] = set()
        self.faces = FaceDiscovery(max_records)
        self._face_settings = dict(entry.data[CONF_CONFIGURATION].get("frigate", {}))
        self._face_task: asyncio.Task | None = None
        self._last_face_request = float("-inf")
        self._face_refresh_pending = False
        self._face_refresh_lock = asyncio.Lock()
        self.face_catalogue_status = "not_configured"
        self._stopping = False
        self.activated_discovery = activated_discovery
        self.pending_discovery = pending_discovery
        self._mqtt_subscribed = False
        self._cancel_expiration: Callable[[], None] | None = None
        self._topic_sources = {
            topic: tuple(
                source.source_id
                for source in configuration.sources
                if source.enabled and topic in source.topics
            )
            for topic in configuration.topics
        }

    async def async_setup(self) -> None:
        """Restore state, subscribe exactly once and seed configured entities."""
        restored = await self._store.async_load()
        if restored:
            self.engine.restore_state(restored)
            self.faces.restore(restored.get("face_discovery"))
            self.coordinator.async_set_updated_data(self.engine.snapshot)

        entity_ids = self.engine.configuration.entity_ids
        if entity_ids:
            self._unsubscribers.append(
                async_track_state_change_event(
                    self.hass,
                    entity_ids,
                    self._async_state_changed,
                )
            )
            missing_source_ids: set[str] = set()
            for entity_id in entity_ids:
                state = self.hass.states.get(entity_id)
                if state is not None:
                    await self._async_process_state(entity_id, state)
                else:
                    missing_source_ids.update(
                        source.source_id
                        for source in self.engine.configuration.sources
                        if entity_id in source.entity_ids
                    )
            if missing_source_ids:
                self.coordinator.async_set_updated_data(
                    self.engine.mark_channel_unavailable(missing_source_ids).snapshot
                )

        if self.engine.configuration.topics and "mqtt" in self.hass.config.components:
            await self._async_subscribe_mqtt()
        elif self.engine.configuration.topics:
            update = self.engine.mark_channel_unavailable(
                source_id
                for source_ids in self._topic_sources.values()
                for source_id in source_ids
            )
            self.coordinator.async_set_updated_data(update.snapshot)

        self._unsubscribers.append(
            self.hass.bus.async_listen(
                er.EVENT_ENTITY_REGISTRY_UPDATED,
                self._async_registry_changed,
            )
        )
        self._schedule_face_refresh()
        self._unsubscribers.append(
            self.hass.bus.async_listen(
                dr.EVENT_DEVICE_REGISTRY_UPDATED,
                self._async_device_registry_changed,
            )
        )
        self._reschedule_expiration()
        self._unsubscribers.append(
            self.hass.bus.async_listen(
                EVENT_COMPONENT_LOADED,
                self._async_component_loaded,
            )
        )

    async def async_shutdown(self) -> None:
        """Remove listeners before final persistence."""
        self._stopping = True
        if self._face_task is not None:
            self._face_task.cancel()
            await asyncio.gather(self._face_task, return_exceptions=True)
            self._face_task = None
        if self._cancel_expiration is not None:
            self._cancel_expiration()
            self._cancel_expiration = None
        while self._unsubscribers:
            self._unsubscribers.pop()()
        self._identity_listeners.clear()
        await self._store.async_save(self._export_state())

    def _export_state(self) -> dict:
        return {**self.engine.export_state(), "face_discovery": self.faces.export()}

    @property
    def identity_ids(self) -> tuple[str, ...]:
        return tuple(sorted(set(self.engine.configuration.identity_ids) | set(self.faces.observed.values())))

    @callback
    def async_add_identity_listener(self, listener: IdentityListener) -> Callable[[], None]:
        self._identity_listeners.add(listener)
        return lambda: self._identity_listeners.discard(listener)

    @callback
    def _schedule_face_refresh(self) -> None:
        if self._stopping or not self._face_settings.get("url"):
            return
        if self._face_task is not None and not self._face_task.done():
            self._face_refresh_pending = True
            return
        self._face_task = self.hass.async_create_task(
            self.async_refresh_faces(), "Presence Engine face catalogue",
        )

    async def async_refresh_faces(self, *, force=False) -> bool:
        """Coalesce bursts and retry only after another meaningful trigger."""
        if force and self._face_task is not None and not self._face_task.done():
            self._face_task.cancel()
            await asyncio.gather(self._face_task, return_exceptions=True)
            self._face_task = None
        if not self._face_settings.get("url") or self._stopping:
            return False
        if not force and monotonic() - self._last_face_request < 60:
            # One coalesced trailing request, not a recurring polling timer.
            await asyncio.sleep(max(0, 60 - (monotonic() - self._last_face_request)))
        async with self._face_refresh_lock:
            self._last_face_request = monotonic()
            self._face_refresh_pending = False
            try:
                payload = await fetch_face_catalogue(self.hass, self._face_settings)
                self.faces.update_catalogue(payload)
            except (ClientError, TimeoutError, ValueError, TypeError, KeyError):
                self.face_catalogue_status = "unavailable"
                # Do not log response bodies, credentials or URLs; preserve metadata.
                _LOGGER.debug("Face catalogue refresh unavailable; detection remains push-only")
                return False
        self.face_catalogue_status = "ready"
        self._store.async_delay_save(self._export_state, self._save_delay_seconds)
        if self._face_refresh_pending:
            self._face_refresh_pending = False
            self._face_task = None
            self._schedule_face_refresh()
        return True

    @callback
    def async_add_detection_listener(self, listener: DetectionListener) -> Callable[[], None]:
        self._detection_listeners.add(listener)

        @callback
        def remove() -> None:
            self._detection_listeners.discard(listener)

        return remove

    @callback
    def _async_state_changed(self, event: Event[EventStateChangedData]) -> None:
        new_state = event.data["new_state"]
        if new_state is None:
            entity_id = event.data["entity_id"]
            source_ids = tuple(
                source.source_id
                for source in self.engine.configuration.sources
                if entity_id in source.entity_ids
            )
            self.hass.async_create_task(
                self._async_state_removed(entity_id, source_ids),
                f"Presence Engine unavailable {entity_id}",
            )
            return
        self.hass.async_create_task(
            self._async_process_state(event.data["entity_id"], new_state),
            f"Presence Engine state {event.data['entity_id']}",
        )

    async def _async_process_state(self, entity_id: str, state: State) -> None:
        envelope = AdapterEnvelope(
            channel_type="state",
            channel=entity_id,
            payload={
                "state": state.state,
                "attributes": dict(state.attributes),
                "last_changed": state.last_changed.isoformat(),
                "last_updated": state.last_updated.isoformat(),
            },
            # Entity adapters consume the state value, not attributes. An
            # attribute-only refresh must not create a semantic revision.
            observed_at=state.last_changed,
            received_at=dt_util.utcnow(),
        )
        await self._async_process(envelope)

    async def _async_state_removed(
        self,
        entity_id: str,
        source_ids: tuple[str, ...],
    ) -> None:
        now = dt_util.utcnow()
        await self._async_process(
            AdapterEnvelope(
                channel_type="state",
                channel=entity_id,
                payload={"state": "unavailable"},
                observed_at=now,
                received_at=now,
            )
        )
        if source_ids:
            await self._async_mark_unavailable(source_ids)

    async def _async_mqtt_message(self, message: Any) -> None:
        try:
            payload = json.loads(message.payload)
        except (json.JSONDecodeError, TypeError):
            _LOGGER.debug("Ignoring invalid JSON on configured topic %s", message.topic)
            return
        if not isinstance(payload, dict):
            return
        now = dt_util.utcnow()
        envelope = AdapterEnvelope("mqtt", message.topic, payload, now, now)
        await self._async_process(envelope)

    async def _async_mark_unavailable(self, source_ids: tuple[str, ...]) -> None:
        async with self._lock:
            update = self.engine.mark_channel_unavailable(source_ids)
            self._publish(update)
            self._store.async_delay_save(self._export_state, self._save_delay_seconds)
            self._reschedule_expiration()

    async def _async_subscribe_mqtt(self) -> None:
        if self._mqtt_subscribed:
            return
        for topic in self.engine.configuration.topics:
            unsubscribe = await mqtt.async_subscribe(
                self.hass,
                topic,
                self._async_mqtt_message,
                qos=0,
                encoding="utf-8",
            )
            self._unsubscribers.append(unsubscribe)
        if self._face_settings.get("url"):
            topic = self._face_settings.get("availability_topic", "frigate/available")
            self._unsubscribers.append(await mqtt.async_subscribe(
                self.hass, topic, self._async_frigate_available, qos=0, encoding="utf-8",
            ))
        self._mqtt_subscribed = True

    @callback
    def _async_frigate_available(self, message) -> None:
        if message.payload == "online":
            self._schedule_face_refresh()

    @callback
    def _async_component_loaded(self, event: Event) -> None:
        if event.data.get("component") != "mqtt" or self._mqtt_subscribed:
            return
        self.hass.async_create_task(
            self._async_subscribe_mqtt(),
            "Presence Engine MQTT subscription",
        )

    @callback
    def _async_registry_changed(self, event: Event) -> None:
        entity_ids = {
            value
            for value in (
                event.data.get("entity_id"),
                event.data.get("old_entity_id"),
            )
            if isinstance(value, str)
        }
        if entity_ids.intersection(self.engine.configuration.entity_ids):
            self.hass.config_entries.async_schedule_reload(self.entry.entry_id)
            return
        current_entity_id = event.data.get("entity_id")
        if not isinstance(current_entity_id, str):
            return
        candidate = next(
            (
                descriptor
                for descriptor in collect_entity_descriptors(self.hass)
                if descriptor.entity_id == current_entity_id
            ),
            None,
        )
        if candidate is not None and discover_candidate(candidate) is not None:
            self.hass.config_entries.async_schedule_reload(self.entry.entry_id)

    @callback
    def _async_device_registry_changed(self, event: Event) -> None:
        """Re-evaluate capabilities and inherited areas after rare registry changes."""
        self.hass.config_entries.async_schedule_reload(self.entry.entry_id)

    async def _async_process(self, envelope: AdapterEnvelope) -> None:
        async with self._lock:
            update = self.engine.process(envelope)
            self._publish(update)
            self._store.async_delay_save(self._export_state, self._save_delay_seconds)
            self._reschedule_expiration()

    async def _async_refresh_expirations(self) -> None:
        async with self._lock:
            update = self.engine.refresh()
            if update.changed:
                self._publish(update)
            self._reschedule_expiration()

    @callback
    def _reschedule_expiration(self) -> None:
        if self._cancel_expiration is not None:
            self._cancel_expiration()
            self._cancel_expiration = None
        expiration = self.engine.next_expiration()
        if expiration is None:
            return
        delay = max(0.0, (expiration - dt_util.utcnow()).total_seconds())

        @callback
        def expired(_: datetime) -> None:
            self._cancel_expiration = None
            self.hass.async_create_task(
                self._async_refresh_expirations(),
                "Presence Engine evidence expiration",
            )

        self._cancel_expiration = async_call_later(self.hass, delay, expired)

    @callback
    def _publish(self, update: RuntimeUpdate) -> None:
        if self._face_settings.get("discover_faces", True):
            for name, identity in update.accepted_faces:
                if self.faces.observe(name, identity):
                    for listener in tuple(self._identity_listeners):
                        listener(identity)
                    self._schedule_face_refresh()
        self.coordinator.async_set_updated_data(update.snapshot)
        for detection in update.detections:
            event_data = detection_payload(detection)
            self.hass.bus.async_fire(EVENT_RESULT, event_data)
            for listener in tuple(self._detection_listeners):
                listener(detection)
