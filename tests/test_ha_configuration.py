"""Native HA checks; also runnable in an isolated HA interpreter without setup/I/O."""

from copy import deepcopy
import importlib.util
import json
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock, Mock, patch

HA_AVAILABLE = importlib.util.find_spec("homeassistant") is not None

if HA_AVAILABLE:
    import homeassistant
    from presence_engine.config_flow import PresenceEngineConfigFlow, PresenceEngineOptionsFlow
    from presence_engine.configuration_ui import EMPTY_CONFIGURATION, source_to_raw
    from presence_engine.const import CONF_CONFIGURATION
    from presence_engine.ha_runtime import HomeAssistantPresenceRuntime
    from presence_engine.sensor import async_setup_entry
    from homeassistant.core import HomeAssistant
    from homeassistant.helpers.config_validation import custom_serializer, to_field_list as convert

from integration_helpers import integration_config
from helpers import at


@unittest.skipUnless(HA_AVAILABLE, "Requires an isolated Home Assistant interpreter")
class NativeConfigurationTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.flow = PresenceEngineConfigFlow()
        self.flow.hass = SimpleNamespace(config_entries=SimpleNamespace(async_entries=lambda *args: []))
        self.flow._descriptors = lambda: ()
        self.flow._areas = lambda: [{"value": "alpha", "label": "Alpha"}]
        self.flow._floors = lambda: ["ground"]
        self.flow._identities = lambda: ["person_a"]
        self.flow._draft = deepcopy(EMPTY_CONFIGURATION)
        self.flow._draft["areas"] = {"alpha": "ground"}
        self.flow._draft["cameras"] = {"cam": {"floor": "ground", "fixed_area": "alpha", "extension": {"preserve": True}}}

    async def test_native_forms_serialize_and_camera_edits_preserve_extensions(self):
        for step in ("user", "areas", "identities", "cameras", "sources", "discovery", "frigate", "advanced", "save", "area_edit", "identity_edit", "source_type"):
            result = await getattr(self.flow, f"async_step_{step}")()
            if "data_schema" in result:
                convert(result["data_schema"], custom_serializer=custom_serializer)
        self.flow._key = "cam"
        result = await self.flow.async_step_camera_edit()
        converted = convert(result["data_schema"], custom_serializer=custom_serializer)
        self.assertTrue(converted)
        values = result["data_schema"]({})
        values["floor"] = "ground"
        result = await self.flow.async_step_camera_edit(values)
        self.assertEqual(result["type"], "menu")
        self.assertEqual(self.flow._draft["cameras"]["cam"]["extension"], {"preserve": True})
        self.assertEqual(self.flow._draft["cameras"]["cam"]["fixed_area"], "alpha")

    async def test_all_source_forms_validate_and_round_trip(self):
        config = integration_config()
        self.flow._draft = {
            **deepcopy(EMPTY_CONFIGURATION), "areas": dict(config.areas),
            "cameras": {"camera_a": {"floor": "floor_alpha"}},
            "sources": [source_to_raw(source) for source in config.sources],
        }
        self.flow._areas = lambda: list(config.areas)
        self.flow._floors = lambda: list(set(config.areas.values()))
        for source in list(self.flow._draft["sources"]):
            self.flow._key = source["source_id"]
            result = await self.flow.async_step_source_edit()
            convert(result["data_schema"], custom_serializer=custom_serializer)
            values = result["data_schema"]({})
            result = await self.flow.async_step_source_edit(values)
            self.assertFalse(result.get("errors"), result)
            stored = next(item for item in self.flow._draft["sources"] if item["source_id"] == source["source_id"])
            self.assertEqual(stored["options"], source["options"])
            self.assertEqual(stored["entity_registry_ids"], source["entity_registry_ids"])
        self.flow._key = ""
        from presence_engine.configuration import AdapterType
        for adapter in AdapterType:
            self.flow._adapter = adapter.value
            result = await self.flow.async_step_source_edit()
            convert(result["data_schema"], custom_serializer=custom_serializer)

    async def test_json_import_is_a_draft_and_preserves_secret(self):
        self.flow._draft["frigate"] = {"url": "https://frigate.local", "username": "user", "password": "not-a-real-secret"}
        exported = await self.flow.async_step_advanced()
        default = next(iter(exported["data_schema"].schema)).default()
        self.assertNotIn("not-a-real-secret", default)
        result = await self.flow.async_step_advanced({CONF_CONFIGURATION: default})
        self.assertEqual(result["type"], "menu")
        self.assertEqual(self.flow._draft["frigate"]["password"], "not-a-real-secret")
        before = deepcopy(self.flow._draft)
        result = await self.flow.async_step_advanced({CONF_CONFIGURATION: "[]"})
        self.assertTrue(result["errors"])
        self.assertEqual(self.flow._draft, before)
        for invalid in (None, [], "invalid", 1):
            result = await self.flow.async_step_advanced({CONF_CONFIGURATION: json.dumps({**before, "frigate": invalid})})
            self.assertTrue(result["errors"])
            self.assertEqual(self.flow._draft, before)

    async def test_identity_entity_selection_updates_and_removes_existing_associations(self):
        from presence_engine.discovery import EntityDescriptor
        descriptor = EntityDescriptor("reg", "sensor.device_area", "bermuda", "device_area", "sensor")
        self.flow._descriptors = lambda: (descriptor,)
        self.flow._draft["identities"] = {descriptor.stable_key: "person_a"}
        self.flow._draft["sources"] = [{"source_id": "device", "adapter": "bermuda_area", "entity_ids": [descriptor.entity_id], "identity": "person_a"}]
        self.flow._key = "person_a"
        result = await self.flow.async_step_identity_edit()
        values = result["data_schema"]({})
        values["entities"] = []
        result = await self.flow.async_step_identity_edit(values)
        self.assertFalse(result.get("errors"), result)
        self.assertNotIn(descriptor.stable_key, self.flow._draft["identities"])
        self.assertIsNone(self.flow._draft["sources"][0]["identity"])
        result = await self.flow.async_step_identity_edit()
        values = result["data_schema"]({})
        values["entities"] = [descriptor.entity_id]
        result = await self.flow.async_step_identity_edit(values)
        self.assertFalse(result.get("errors"), result)
        self.assertEqual(self.flow._draft["identities"][descriptor.stable_key], "person_a")
        self.assertEqual(self.flow._draft["sources"][0]["identity"], "person_a")
        self.flow._reconfiguring = True
        self.flow._get_reconfigure_entry = lambda: SimpleNamespace(runtime_data=SimpleNamespace(faces=SimpleNamespace(catalogue=[], observed={"New Face": "New Face"})))
        result = await self.flow.async_step_identity_edit()
        control = next(control for marker, control in result["data_schema"].schema.items() if marker.schema == "face_names")
        self.assertIn("New Face", control.config["options"])

    async def test_native_reconfigure_does_not_write_before_save(self):
        entry = SimpleNamespace(data={CONF_CONFIGURATION: deepcopy(self.flow._draft)})
        self.flow._get_reconfigure_entry = lambda: entry
        self.flow.async_update_reload_and_abort = Mock(return_value={"type": "abort"})
        await self.flow.async_step_reconfigure()
        self.flow._draft["extension"] = True
        self.assertNotIn("extension", entry.data[CONF_CONFIGURATION])
        await self.flow.async_step_save({})
        self.flow.async_update_reload_and_abort.assert_called_once()

    async def test_face_entities_are_created_only_after_acceptance_and_without_duplicates(self):
        hass = HomeAssistant("/tmp/presence-engine-no-io")
        entry = SimpleNamespace(entry_id="isolated", data={CONF_CONFIGURATION: {}}, options={}, async_on_unload=Mock())
        runtime = HomeAssistantPresenceRuntime(hass, entry, integration_config(), max_records=2000, save_delay_seconds=15)
        runtime._store = Mock()
        runtime._store.async_save = AsyncMock()
        runtime._reschedule_expiration = Mock()
        entry.runtime_data = runtime
        added = []
        await async_setup_entry(hass, entry, lambda entities: added.extend(entities))
        before = len(added)
        runtime.faces.update_catalogue({"New Face": []})
        self.assertEqual(len(added), before)
        from presence_engine.adapters import AdapterEnvelope
        payload = {"type": "face", "id": "new-face", "camera": "camera_a", "name": "New Face", "score": 0.1, "timestamp": at(2).timestamp()}
        await runtime._async_process(AdapterEnvelope("mqtt", "frigate/tracked_object_update", payload, at(2), at(2)))
        self.assertEqual(len(added), before)
        payload["score"] = 0.95
        await runtime._async_process(AdapterEnvelope("mqtt", "frigate/tracked_object_update", payload, at(2), at(2)))
        self.assertEqual(len(added), before + 1)
        await runtime._async_process(AdapterEnvelope("mqtt", "frigate/tracked_object_update", payload, at(2), at(2)))
        self.assertEqual(len(added), before + 1)
        self.assertIn("New Face", runtime._export_state()["face_discovery"]["observed"])
        await runtime.async_shutdown()

    async def test_catalogue_failure_preserves_data_and_never_creates_presence(self):
        hass = HomeAssistant("/tmp/presence-engine-no-io")
        entry = SimpleNamespace(entry_id="isolated", data={CONF_CONFIGURATION: {"frigate": {"url": "http://frigate.local"}}}, options={}, async_on_unload=Mock())
        runtime = HomeAssistantPresenceRuntime(hass, entry, integration_config(), max_records=2000, save_delay_seconds=15)
        runtime._store = Mock()
        runtime._store.async_save = AsyncMock()
        runtime.faces.update_catalogue({"Registered Face": []})
        with patch("presence_engine.ha_runtime.fetch_face_catalogue", side_effect=TimeoutError):
            self.assertFalse(await runtime.async_refresh_faces(force=True))
        self.assertEqual(runtime.faces.catalogue, ["Registered Face"])
        self.assertEqual(runtime.engine.snapshot.count_minimum, 0)
        self.assertEqual(runtime.faces.observed, {})
        self.assertEqual(runtime.face_catalogue_status, "unavailable")
        await runtime.async_shutdown()

    async def test_catalogue_request_is_coalesced_and_cancelled_on_unload(self):
        import asyncio
        hass = HomeAssistant("/tmp/presence-engine-no-io")
        entry = SimpleNamespace(entry_id="isolated", data={CONF_CONFIGURATION: {"frigate": {"url": "http://frigate.local"}}}, options={}, async_on_unload=Mock())
        runtime = HomeAssistantPresenceRuntime(hass, entry, integration_config(), max_records=2000, save_delay_seconds=15)
        runtime._store = Mock(async_save=AsyncMock())
        release = asyncio.Event()
        async def fetch(*args):
            await release.wait()
            return {"Registered Face": []}
        with patch("presence_engine.ha_runtime.fetch_face_catalogue", side_effect=fetch) as mock_fetch:
            runtime._schedule_face_refresh()
            first = runtime._face_task
            for _ in range(20):
                runtime._async_frigate_available(SimpleNamespace(payload="online"))
            self.assertIs(runtime._face_task, first)
            release.set()
            await first
            self.assertEqual(mock_fetch.call_count, 1)
            self.assertEqual(runtime.faces.observed, {})
            runtime._schedule_face_refresh()
            pending = runtime._face_task
            await runtime.async_shutdown()
            self.assertTrue(pending.cancelled())

    async def test_authenticated_http_catalogue_uses_only_memory_and_complete_chunks(self):
        from http.cookies import SimpleCookie
        from presence_engine.ha_face_catalogue import _fetch
        class Response:
            status = 200
            cookies = SimpleCookie("frigate_token=fixture-token")
            content = None
            async def __aenter__(self): return self
            async def __aexit__(self, *args): pass
            def raise_for_status(self): pass
            async def iter_chunked(self, size):
                yield b'{"New '
                yield b'Face": ["a.webp"]}'
        response = Response()
        response.content = response
        session = Mock(post=Mock(return_value=response), get=Mock(return_value=response))
        result = await _fetch(session, {"url": "https://frigate.local", "username": "fixture-user", "password": "fixture-password"})
        self.assertEqual(result, {"New Face": ["a.webp"]})
        self.assertEqual(session.get.call_args.args, ("https://frigate.local/api/faces",))
        self.assertEqual(session.get.call_args.kwargs["headers"], {"Authorization": "Bearer fixture-token"})
