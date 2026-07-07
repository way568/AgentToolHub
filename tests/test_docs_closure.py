import unittest
from pathlib import Path


class DocsClosureTests(unittest.TestCase):
    def test_readme_covers_structure_commands_and_boundaries(self):
        readme = Path("README.md").read_text(encoding="utf-8")

        self.assertIn("AgentToolHub", readme)
        self.assertIn("agent-tool-hub doctor", readme)
        self.assertIn("agent-tool-hub mcp test --name", readme)
        self.assertIn("agent-tool-hub skills gather", readme)
        self.assertIn("agent-tool-hub skills toggle", readme)
        self.assertIn("pip install .", readme)
        self.assertIn("pyproject.toml", readme)
        self.assertIn("127.0.0.1", readme)
        self.assertIn("fetch_tools", readme)
        self.assertIn("Developer Compatibility Notes", readme)
        self.assertIn("tool_hub/data/", readme)
        self.assertIn("tool_hub_server.py", readme)
        self.assertIn("QUICKSTART.md", readme)

    def test_quickstart_covers_release_basics(self):
        quickstart = Path("QUICKSTART.md").read_text(encoding="utf-8")

        self.assertIn("怎么解压即用", quickstart)
        self.assertIn("怎么初始化", quickstart)
        self.assertIn("常见命令", quickstart)
        self.assertIn("常见错误", quickstart)
        self.assertIn("python3 tool_hub_server.py", quickstart)
        self.assertIn("python3 -m tool_hub.cli doctor", quickstart)
        self.assertIn("skills gather", quickstart)
        self.assertIn("127.0.0.1", quickstart)

    def test_handoff_reflects_current_package_and_remaining_work(self):
        handoff = Path("HANDOFF.md").read_text(encoding="utf-8")

        self.assertIn("Phase 0~7", handoff)
        self.assertIn("tool_hub/http_app.py", handoff)
        self.assertIn("tool_hub/services/skills.py", handoff)
        self.assertIn("tool_hub/services/audit.py", handoff)
        self.assertIn("tool_hub/services/config.py", handoff)
        self.assertIn("tool_hub/services/upload.py", handoff)
        self.assertIn("pyproject.toml", handoff)
        self.assertIn("AgentToolHub", handoff)
        self.assertIn("agent-tool-hub", handoff)
        self.assertIn("agent-tool-hub-web", handoff)
        self.assertIn("agent-tool-dock", handoff)
        self.assertIn("agent-tool-dock-web", handoff)
        self.assertIn("tool-hub", handoff)
        self.assertIn("tool-hub-web", handoff)
        self.assertIn("python3 -m unittest discover -s tests -v", handoff)
        self.assertIn("data/agent-presets/", handoff)
        self.assertIn("README.md", handoff)
        self.assertIn("发布", handoff)


if __name__ == "__main__":
    unittest.main()
