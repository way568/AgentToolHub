import tempfile
import unittest
from types import SimpleNamespace
from pathlib import Path
from unittest.mock import patch


class Phase3SafetyTests(unittest.TestCase):
    def test_write_agent_mcp_entry_creates_backup_before_write(self):
        from tool_hub.mcp.agent_config import write_agent_mcp_entry

        with tempfile.TemporaryDirectory() as tmp:
            config_path = Path(tmp) / "config.toml"
            config_path.write_text('model = "gpt-5"\n', encoding="utf-8")
            agent = {
                "id": "codex",
                "mcp_config_path": str(config_path),
                "mcp_config_key": "mcp_servers",
            }

            self.assertTrue(
                write_agent_mcp_entry(
                    agent,
                    "playwright",
                    {"command": "npx", "args": ["@playwright/mcp@latest"]},
                )
            )

            backups = sorted(config_path.parent.glob("config.toml.bak-*"))
            self.assertTrue(backups)

    def test_agent_service_rejects_invalid_agent_id(self):
        from tool_hub.errors import ToolHubError
        from tool_hub.services.agents import AgentService

        with self.assertRaises(ToolHubError):
            AgentService().build_agent_from_body(
                {
                    "id": "../escape",
                    "name": "Bad Agent",
                    "skills_dir": ["/tmp/skills"],
                }
            )

    def test_skill_service_delete_rejects_escape_path(self):
        from tool_hub.errors import ToolHubError
        from tool_hub.services.skills import SkillService

        with tempfile.TemporaryDirectory() as tmp:
            hub_path = Path(tmp) / "hub"
            hub_path.mkdir(parents=True, exist_ok=True)
            config = {"hub_path": str(hub_path)}

            with self.assertRaises(ToolHubError):
                SkillService().delete_skill(config, "../escape")

    def test_stdio_test_does_not_fetch_tools_description_by_default(self):
        from tool_hub.mcp.store import save_mcp
        from tool_hub.services.mcp import McpService

        with tempfile.TemporaryDirectory() as tmp:
            hub_path = Path(tmp) / "hub"
            save_mcp(
                str(hub_path),
                {
                    "name": "local-stdio",
                    "type": "stdio",
                    "command": "python3",
                    "args": ["-V"],
                },
            )
            config = {"hub_path": str(hub_path), "agents": []}

            with patch("tool_hub.services.mcp.fetch_mcp_tools_description") as fetch_mock:
                result = McpService().test_mcp(config, "local-stdio")

            self.assertIn(result["status"], {"ok", "error"})
            fetch_mock.assert_not_called()

    def test_save_mcp_creates_backup_before_overwrite(self):
        from tool_hub.mcp.store import save_mcp

        with tempfile.TemporaryDirectory() as tmp:
            save_mcp(
                tmp,
                {
                    "name": "playwright",
                    "type": "stdio",
                    "command": "npx",
                    "args": ["@playwright/mcp@latest"],
                },
            )

            save_mcp(
                tmp,
                {
                    "name": "playwright",
                    "type": "stdio",
                    "command": "node",
                    "args": ["server.js"],
                },
            )

            backups = sorted((Path(tmp) / "mcp").glob("playwright.json.bak-*"))
            self.assertTrue(backups)

    def test_http_app_main_binds_localhost(self):
        from tool_hub import http_app

        fake_server = SimpleNamespace(
            serve_forever=lambda: (_ for _ in ()).throw(KeyboardInterrupt()),
            shutdown=lambda: None,
        )

        with patch("tool_hub.http_app._startup_network_check", return_value={"port_available": True, "port_error": None, "active_proxies": {}}), patch(
            "tool_hub.http_app.load_config", return_value=None
        ), patch("tool_hub.http_app.HTTPServer", return_value=fake_server) as server_ctor, patch(
            "tool_hub.http_app.webbrowser.open"
        ):
            http_app.main()

        self.assertEqual(server_ctor.call_args.args[0][0], "127.0.0.1")


if __name__ == "__main__":
    unittest.main()
