from copy import deepcopy
import unittest

from presence_engine.configuration import ConfigurationError, parse_configuration
from presence_engine.configuration_ui import (
    EMPTY_CONFIGURATION, bind_entities, delete_item, patch_item, rows_mapping,
    source_to_raw, validate_draft,
)
from presence_engine.discovery import EntityDescriptor, apply_discovery
from presence_engine.face_discovery import FaceDiscovery

from integration_helpers import integration_config


class ConfigurationUITests(unittest.TestCase):
    def test_lossless_patch_and_disabled_discovery_binding(self):
        raw = deepcopy(EMPTY_CONFIGURATION)
        raw["areas"] = {"alpha": "ground"}
        raw["extension"] = {"preserve": True}
        raw["sources"] = [{"source_id": "radar", "adapter": "binary_presence", "entity_ids": ["binary_sensor.radar"], "area": "alpha", "options": {"extension": 42}}]
        patched = patch_item(raw, "sources", "radar", {"enabled": False})
        validate_draft(patched)
        self.assertTrue(patched["extension"]["preserve"])
        self.assertEqual(patched["sources"][0]["options"], {"extension": 42})
        self.assertNotIn("enabled", raw["sources"][0])
        descriptor = EntityDescriptor("reg", "binary_sensor.radar", "esphome", "radar_presence", "binary_sensor", area_id="alpha")
        plan = apply_discovery(parse_configuration(patched), [descriptor])
        self.assertEqual(plan.activated, ())
        self.assertEqual(len(plan.configuration.sources), 1)
        with self.assertRaises(ConfigurationError):
            delete_item(raw, "areas", "alpha")

    def test_bindings_refresh_and_discovered_source_round_trip(self):
        descriptor = EntityDescriptor("reg", "binary_sensor.radar", "esphome", "radar_presence", "binary_sensor", area_id="alpha")
        item = {"entity_ids": ["binary_sensor.old"], "entity_registry_ids": ["old"]}
        bind_entities(item, "entity_ids", "entity_registry_ids", [descriptor.entity_id], [descriptor])
        self.assertEqual(item["entity_registry_ids"], ["reg"])
        raw = deepcopy(EMPTY_CONFIGURATION)
        raw["areas"] = {"alpha": "ground"}
        plan = apply_discovery(parse_configuration(raw), [descriptor])
        raw["sources"] = [source_to_raw(plan.configuration.sources[0])]
        validate_draft(raw)

    def test_duplicate_mapping_keys_and_missing_adapter_options_are_rejected(self):
        with self.assertRaises(ConfigurationError):
            rows_mapping([{"key": "a", "value": "b"}, {"key": "a", "value": "c"}])
        raw = deepcopy(EMPTY_CONFIGURATION)
        raw["sources"] = [{"source_id": "face", "adapter": "frigate_face", "topics": ["frigate/tracked_object_update"]}]
        with self.assertRaises(ValueError):
            validate_draft(raw)

    def test_frigate_settings_do_not_change_evidence_contract(self):
        raw = deepcopy(EMPTY_CONFIGURATION)
        raw["frigate"] = {"url": "http://frigate.local:5000", "discover_faces": True}
        validate_draft(raw)
        for url in ("file:///tmp/faces", "https://user:pass@frigate.local", "http://frigate.local?secret=a"):
            raw["frigate"]["url"] = url
            with self.assertRaises(ConfigurationError):
                validate_draft(raw)

    def test_catalogue_is_not_observation_and_failed_updates_preserve_metadata(self):
        faces = FaceDiscovery()
        faces.update_catalogue({"New Face": ["a.webp"]})
        self.assertEqual(faces.observed, {})
        self.assertTrue(faces.observe("New Face", "new_identity"))
        self.assertFalse(faces.observe("New Face", "new_identity"))
        with self.assertRaises(ValueError):
            faces.update_catalogue({"New Face": "invalid"})
        self.assertEqual(faces.catalogue, ["New Face"])
        faces.update_catalogue({})
        self.assertEqual(faces.observed, {"New Face": "new_identity"})
        restored = FaceDiscovery()
        restored.restore(faces.export())
        self.assertEqual(restored.observed, faces.observed)

    def test_accepted_face_discovery_uses_the_existing_adapter_guards(self):
        from presence_engine.runtime import PresenceRuntime
        from presence_engine.adapters import AdapterEnvelope
        from helpers import at
        runtime = PresenceRuntime(integration_config(), now=lambda: at(10))
        def face(score, name="New Face"):
            return runtime.process(AdapterEnvelope("mqtt", "frigate/tracked_object_update", {"type": "face", "name": name, "score": score, "id": "new-event", "camera": "camera_a", "timestamp": at(2).timestamp()}, at(2), at(2)))
        self.assertEqual(face(0.1).accepted_faces, ())
        self.assertEqual(face(0.9, None).accepted_faces, ())
        self.assertEqual(face(0.9).accepted_faces, (("New Face", "New Face"),))
        raw = deepcopy(EMPTY_CONFIGURATION)
        raw["areas"] = {"alpha": "ground"}
        raw["cameras"] = {"camera_a": {"floor": "ground", "zone_to_area": {"zone_a": "alpha"}, "admission_mode": "mapped_current_zone"}}
        raw["sources"] = [{"source_id": "faces", "adapter": "frigate_face", "topics": ["frigate/tracked_object_update"], "options": {"recognition_threshold": 0.8}}]
        runtime = PresenceRuntime(parse_configuration(raw), now=lambda: at(10))
        self.assertEqual(face(0.9).accepted_faces, ())
