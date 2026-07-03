import json
import tempfile
import unittest
from pathlib import Path


class Phase5RegistryTests(unittest.TestCase):
    def test_presets_load_from_json_directory(self):
        from tool_hub import presets

        with tempfile.TemporaryDirectory() as tmp:
            preset_dir = Path(tmp)
            (preset_dir / "demo.json").write_text(
                json.dumps(
                    {
                        "id": "demo",
                        "name": "Demo",
                        "skills_dir_candidates": ["/tmp/demo-skills"],
                        "mcp_config_candidates": ["/tmp/demo.json"],
                        "mcp_config_key": "mcpServers",
                    }
                ),
                encoding="utf-8",
            )

            loaded = presets.load_agent_presets(preset_dir)

        self.assertEqual(len(loaded), 1)
        self.assertEqual(loaded[0]["id"], "demo")

    def test_backend_registry_resolves_json_and_toml(self):
        from tool_hub.backends.registry import get_backend_for_agent

        json_backend = get_backend_for_agent({"mcp_config_path": "/tmp/demo.json"})
        toml_backend = get_backend_for_agent({"mcp_config_path": "/tmp/demo.toml"})

        self.assertEqual(json_backend.name, "json")
        self.assertEqual(toml_backend.name, "toml")

    def test_skill_backend_registry_resolves_directory_symlink(self):
        from tool_hub.skills.backends import get_skill_backend

        backend = get_skill_backend("directory_symlink")

        self.assertEqual(backend.name, "directory_symlink")

    def test_adapter_read_mapping_handles_http_headers(self):
        from tool_hub.mcp.adapters import parse_agent_mcp_to_standard

        parsed = parse_agent_mcp_to_standard(
            "remote-http",
            {
                "type": "streamableHttp",
                "url": "https://example.com/mcp",
                "http_headers": {"Authorization": "Bearer token"},
            },
            agent_id="codex",
        )

        self.assertEqual(parsed["headers"]["Authorization"], "Bearer token")


if __name__ == "__main__":
    unittest.main()
