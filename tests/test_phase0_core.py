import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch


class Phase0CoreTests(unittest.TestCase):
    def test_detect_agents_finds_codex_from_home_layout(self):
        from tool_hub import presets

        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp)
            (home / ".codex" / "skills").mkdir(parents=True)
            (home / ".codex" / "config.toml").write_text("", encoding="utf-8")

            with patch.object(presets, "_home", return_value=home):
                agents = presets.detect_agents()

        codex = next((agent for agent in agents if agent["id"] == "codex"), None)
        self.assertIsNotNone(codex)
        self.assertEqual(codex["name"], "Codex")
        self.assertEqual(codex["skills_dir"], [str(home / ".codex" / "skills")])
        self.assertEqual(codex["mcp_config_path"], str(home / ".codex" / "config.toml"))
        self.assertEqual(codex["mcp_config_key"], "mcp_servers")

    def test_toml_roundtrip_via_agent_config(self):
        from tool_hub.mcp.agent_config import (
            read_agent_mcp_config,
            remove_agent_mcp_entry,
            write_agent_mcp_entry,
        )

        with tempfile.TemporaryDirectory() as tmp:
            config_path = Path(tmp) / "config.toml"
            config_path.write_text('model = "gpt-5"\n', encoding="utf-8")
            agent = {
                "id": "codex",
                "mcp_config_path": str(config_path),
                "mcp_config_key": "mcp_servers",
            }
            mcp_config = {
                "command": "npx",
                "args": ["-y", "@playwright/mcp@latest"],
                "env": {"PLAYWRIGHT_HEADLESS": "1"},
            }

            self.assertTrue(write_agent_mcp_entry(agent, "playwright", mcp_config))
            loaded = read_agent_mcp_config(agent)
            self.assertEqual(loaded["playwright"]["command"], "npx")
            self.assertEqual(loaded["playwright"]["args"], ["-y", "@playwright/mcp@latest"])
            self.assertEqual(loaded["playwright"]["env"]["PLAYWRIGHT_HEADLESS"], "1")

            self.assertTrue(remove_agent_mcp_entry(agent, "playwright"))
            self.assertNotIn("playwright", read_agent_mcp_config(agent))

    def test_codex_adapter_maps_headers_to_http_headers(self):
        from tool_hub.mcp.adapters import adapt_mcp_for_agent

        result = adapt_mcp_for_agent(
            {
                "name": "remote-http",
                "type": "streamableHttp",
                "url": "https://example.com/mcp",
                "headers": {"Authorization": "Bearer token"},
            },
            "codex",
        )

        self.assertEqual(result["type"], "streamableHttp")
        self.assertEqual(result["url"], "https://example.com/mcp")
        self.assertEqual(result["http_headers"], {"Authorization": "Bearer token"})
        self.assertNotIn("headers", result)

    def test_save_delete_mcp_rejects_invalid_name(self):
        from tool_hub.mcp.store import delete_mcp, save_mcp

        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(ValueError):
                save_mcp(tmp, {"name": "../escape", "type": "stdio", "command": "echo", "args": []})

            with self.assertRaises(ValueError):
                delete_mcp(tmp, "../escape")

    def test_save_mcp_persists_clean_payload(self):
        from tool_hub.mcp.store import delete_mcp, load_all_mcp, save_mcp

        with tempfile.TemporaryDirectory() as tmp:
            save_mcp(
                tmp,
                {
                    "name": "playwright",
                    "type": "stdio",
                    "command": "npx",
                    "args": ["@playwright/mcp@latest"],
                    "_internal": "skip-me",
                },
            )

            items = load_all_mcp(tmp)
            self.assertEqual(len(items), 1)
            self.assertEqual(items[0]["name"], "playwright")
            self.assertNotIn("_internal", items[0])

            self.assertTrue(delete_mcp(tmp, "playwright"))
            self.assertEqual(load_all_mcp(tmp), [])


if __name__ == "__main__":
    unittest.main()
