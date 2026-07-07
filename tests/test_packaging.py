import unittest
from pathlib import Path


class PackagingTests(unittest.TestCase):
    def test_pyproject_declares_installable_entrypoints(self):
        pyproject = Path("pyproject.toml").read_text(encoding="utf-8")

        self.assertIn('name = "agent-tool-hub"', pyproject)
        self.assertIn('license = { file = "LICENSE" }', pyproject)
        self.assertIn('agent-tool-hub = "tool_hub.cli:main"', pyproject)
        self.assertIn('agent-tool-hub-web = "tool_hub.server:main"', pyproject)
        self.assertIn('agent-tool-dock = "tool_hub.cli:main"', pyproject)
        self.assertIn('agent-tool-dock-web = "tool_hub.server:main"', pyproject)
        self.assertIn('tool-hub = "tool_hub.cli:main"', pyproject)
        self.assertIn('tool-hub-web = "tool_hub.server:main"', pyproject)
        self.assertIn('"data/agent-presets/*.json"', pyproject)
        self.assertIn('"data/mcp-adapters/*.json"', pyproject)


if __name__ == "__main__":
    unittest.main()
