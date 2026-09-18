from __future__ import annotations

import ast
import unittest
from pathlib import Path


class IndependenceTests(unittest.TestCase):
    def test_core_has_no_platform_or_network_imports(self) -> None:
        source_root=Path(__file__).resolve().parents[1]/"src"/"presence_engine"
        forbidden={"homeassistant","paho","requests","httpx","aiohttp","socket","urllib"}
        found=[]
        for path in source_root.glob("*.py"):
            tree=ast.parse(path.read_text(encoding="utf-8"),filename=str(path))
            for node in ast.walk(tree):
                if isinstance(node,ast.Import):
                    names={alias.name.split(".",1)[0] for alias in node.names}
                elif isinstance(node,ast.ImportFrom) and node.module:
                    names={node.module.split(".",1)[0]}
                else:
                    continue
                if names & forbidden:
                    found.append((path.name,sorted(names & forbidden)))
        self.assertEqual(found,[])

    def test_core_does_not_contain_installation_identifiers(self) -> None:
        source_root=Path(__file__).resolve().parents[1]/"src"/"presence_engine"
        forbidden=("sensor.","binary_sensor.","device_tracker.","frigate/","mqtt")
        hits=[]
        for path in source_root.glob("*.py"):
            text=path.read_text(encoding="utf-8").lower()
            for value in forbidden:
                if value in text:
                    hits.append((path.name,value))
        self.assertEqual(hits,[])


if __name__ == "__main__":
    unittest.main()
