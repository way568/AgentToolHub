import unittest
from pathlib import Path


class DocsClosureTests(unittest.TestCase):
    def test_readme_covers_structure_commands_and_boundaries(self):
        readme = Path("README.md").read_text(encoding="utf-8")

        self.assertIn("tool_hub/", readme)
        self.assertIn("python3 -m tool_hub.cli doctor", readme)
        self.assertIn("python3 -m tool_hub.cli mcp test --name", readme)
        self.assertIn("python3 -m tool_hub.cli skills gather", readme)
        self.assertIn("python3 -m tool_hub.cli skills toggle", readme)
        self.assertIn("pip install .", readme)
        self.assertIn("pyproject.toml", readme)
        self.assertIn("127.0.0.1", readme)
        self.assertIn("fetch_tools", readme)
        self.assertIn("agent-presets/", readme)
        self.assertIn("tool_hub/http_app.py", readme)
        self.assertIn("tool_hub/services/config.py", readme)
        self.assertIn("tool_hub/services/upload.py", readme)

    def test_handoff_reflects_current_package_and_remaining_work(self):
        handoff = Path("HANDOFF.md").read_text(encoding="utf-8")

        self.assertIn("Phase 0~7", handoff)
        self.assertIn("tool_hub/http_app.py", handoff)
        self.assertIn("tool_hub/services/skills.py", handoff)
        self.assertIn("tool_hub/services/audit.py", handoff)
        self.assertIn("tool_hub/services/config.py", handoff)
        self.assertIn("tool_hub/services/upload.py", handoff)
        self.assertIn("pyproject.toml", handoff)
        self.assertIn("tool-hub", handoff)
        self.assertIn("tool-hub-web", handoff)
        self.assertIn("python3 -m unittest discover -s tests -v", handoff)
        self.assertIn("agent-presets/", handoff)
        self.assertIn("README.md", handoff)
        self.assertIn("发布", handoff)


if __name__ == "__main__":
    unittest.main()
