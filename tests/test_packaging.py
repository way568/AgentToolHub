import unittest
from pathlib import Path


class PackagingTests(unittest.TestCase):
    def test_pyproject_declares_installable_entrypoints(self):
        pyproject = Path("pyproject.toml").read_text(encoding="utf-8")

        self.assertIn('name = "tool-hub"', pyproject)
        self.assertIn('tool-hub = "tool_hub.cli:main"', pyproject)
        self.assertIn('tool-hub-web = "tool_hub.server:main"', pyproject)


if __name__ == "__main__":
    unittest.main()
