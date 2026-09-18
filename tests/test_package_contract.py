from __future__ import annotations

import json
from pathlib import Path
import unittest

from presence_engine.configuration import parse_configuration
from presence_engine.const import CONFIG_SCHEMA_VERSION, CONTRACT_VERSION


ROOT = Path(__file__).resolve().parents[1]
COMPONENT = ROOT / "custom_components" / "presence_engine"


class PackageContractTests(unittest.TestCase):
    def test_manifest_and_translations_are_valid_json(self) -> None:
        manifest = json.loads((COMPONENT / "manifest.json").read_text(encoding="utf-8"))
        strings = json.loads((COMPONENT / "strings.json").read_text(encoding="utf-8"))
        english = json.loads(
            (COMPONENT / "translations" / "en.json").read_text(encoding="utf-8")
        )

        self.assertEqual(manifest["domain"], "presence_engine")
        self.assertTrue(manifest["config_flow"])
        self.assertEqual(strings, english)

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

    def test_services_document_both_read_only_queries(self) -> None:
        services = (COMPONENT / "services.yaml").read_text(encoding="utf-8")

        self.assertIn("get_snapshot:", services)
        self.assertIn("get_detection:", services)


if __name__ == "__main__":
    unittest.main()
