from __future__ import annotations

import json
from pathlib import Path
import tomllib
import unittest

from presence_engine import _stable_public_unique_id
from presence_engine.configuration import parse_configuration
from presence_engine.const import (
    CONFIG_SCHEMA_VERSION,
    CONTRACT_VERSION,
    INTEGRATION_VERSION,
    PLATFORMS,
)


ROOT = Path(__file__).resolve().parents[1]
COMPONENT = ROOT / "custom_components" / "presence_engine"


class PackageContractTests(unittest.TestCase):
    def test_manifest_and_translations_are_valid_json(self) -> None:
        manifest = json.loads((COMPONENT / "manifest.json").read_text(encoding="utf-8"))
        hacs = json.loads((ROOT / "hacs.json").read_text(encoding="utf-8"))
        strings = json.loads((COMPONENT / "strings.json").read_text(encoding="utf-8"))
        english = json.loads(
            (COMPONENT / "translations" / "en.json").read_text(encoding="utf-8")
        )
        project = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))

        self.assertEqual(manifest["domain"], "presence_engine")
        self.assertTrue(manifest["config_flow"])
        self.assertEqual(
            manifest["documentation"],
            "https://github.com/dbustosrc/presence-engine",
        )
        self.assertEqual(
            manifest["issue_tracker"],
            "https://github.com/dbustosrc/presence-engine/issues",
        )
        self.assertEqual(manifest["codeowners"], ["@dbustosrc"])
        self.assertEqual(hacs["name"], manifest["name"])
        self.assertEqual(hacs["homeassistant"], "2026.9.2")
        self.assertEqual(strings, english)
        self.assertEqual(manifest["version"], INTEGRATION_VERSION)
        self.assertEqual(project["project"]["version"], INTEGRATION_VERSION)

    def test_neutral_example_is_accepted_by_current_schema(self) -> None:
        raw = json.loads(
            (ROOT / "docs" / "configuration.example.json").read_text(encoding="utf-8")
        )
        configuration = parse_configuration(raw)

        self.assertEqual(configuration.schema_version, CONFIG_SCHEMA_VERSION)
        self.assertEqual(CONTRACT_VERSION, 1)
        self.assertEqual(len(configuration.sources), 5)

    def test_component_does_not_use_internal_or_global_state_listeners(self) -> None:
        python_source = "\n".join(
            path.read_text(encoding="utf-8")
            for path in COMPONENT.rglob("*.py")
        )

        self.assertNotIn("async_subscribe_internal", python_source)
        self.assertNotIn("EVENT_STATE_CHANGED", python_source)
        self.assertIn("async_track_state_change_event", python_source)

    def test_entity_state_semantics_use_last_changed(self) -> None:
        runtime_source = (COMPONENT / "ha_runtime.py").read_text(encoding="utf-8")

        self.assertIn("observed_at=state.last_changed", runtime_source)
        self.assertNotIn("observed_at=state.last_updated", runtime_source)

    def test_services_document_both_read_only_queries(self) -> None:
        services = (COMPONENT / "services.yaml").read_text(encoding="utf-8")

        self.assertIn("get_snapshot:", services)
        self.assertIn("get_detection:", services)

    def test_comparison_package_has_no_external_effect_api(self) -> None:
        python_source = "\n".join(
            path.read_text(encoding="utf-8")
            for path in COMPONENT.rglob("*.py")
        )

        forbidden = (
            "mqtt.async_publish",
            "async_publish(",
            "hass.services.async_call",
            "device_tracker.see",
            "notify.notify",
            "select.select_option",
        )
        for token in forbidden:
            with self.subTest(token=token):
                self.assertNotIn(token, python_source)

    def test_room_projection_uses_records_not_deprecated_trackers(self) -> None:
        init_source = (COMPONENT / "__init__.py").read_text(encoding="utf-8")
        sensor_source = (COMPONENT / "sensor.py").read_text(encoding="utf-8")
        coverage_source = (COMPONENT / "binary_sensor.py").read_text(encoding="utf-8")

        self.assertNotIn("device_tracker", PLATFORMS)
        self.assertFalse((COMPONENT / "device_tracker.py").exists())
        self.assertIn("_migrate_public_projection_registry", init_source)
        self.assertIn('"_tracker_candidate", "_coverage_candidate"', init_source)
        self.assertNotIn("PresenceCandidateSensor", sensor_source)
        self.assertNotIn("RecordCandidateSensor", sensor_source)
        self.assertNotIn("PresenceCoverageCandidateSensor", coverage_source)

    def test_pre_0_4_public_unique_ids_migrate_without_identity_loss(self) -> None:
        entry_id = "entry-a"

        self.assertEqual(
            _stable_public_unique_id("entry-a_presence_candidate", entry_id),
            "entry-a_presence",
        )
        self.assertEqual(
            _stable_public_unique_id("entry-a_person_alpha_record_candidate", entry_id),
            "entry-a_person_alpha_record",
        )
        self.assertIsNone(
            _stable_public_unique_id("entry-a_coverage_candidate", entry_id)
        )
        self.assertIsNone(_stable_public_unique_id("other_presence_candidate", entry_id))

    def test_release_documentation_is_present(self) -> None:
        for relative_path in (
            "CHANGELOG.md",
            "docs/installation.md",
            "docs/comparison.md",
            "docs/rollback.md",
            "docs/public-projections.md",
        ):
            with self.subTest(relative_path=relative_path):
                self.assertTrue((ROOT / relative_path).is_file())


if __name__ == "__main__":
    unittest.main()
