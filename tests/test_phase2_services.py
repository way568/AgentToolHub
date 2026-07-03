import json
import tempfile
import unittest
from pathlib import Path


class Phase2ServiceTests(unittest.TestCase):
    def test_agent_service_adds_agent_and_persists_config(self):
        from tool_hub.config_store import load_config
        from tool_hub.services.agents import AgentService

        with tempfile.TemporaryDirectory() as tmp:
            hub_path = Path(tmp) / "hub"
            config = {
                "hub_path": str(hub_path),
                "agents": [],
                "skills": {},
                "global_exclude": [],
            }
            service = AgentService()

            result = service.add_agent(
                config,
                {
                    "name": "Cursor",
                    "skills_dir": ["/tmp/cursor-skills"],
                    "mcp_config_path": "/tmp/cursor-mcp.json",
                },
            )

            self.assertTrue(result["ok"])
            self.assertEqual(result["agent"]["id"], "cursor")
            stored = load_config(str(hub_path))
            self.assertEqual(stored["agents"][0]["name"], "Cursor")

    def test_mcp_service_adds_and_enables_codex_target(self):
        from tool_hub.mcp.agent_config import read_agent_mcp_config
        from tool_hub.services.mcp import McpService

        with tempfile.TemporaryDirectory() as tmp:
            hub_path = Path(tmp) / "hub"
            codex_config = Path(tmp) / "config.toml"
            codex_config.write_text('model = "gpt-5"\n', encoding="utf-8")
            config = {
                "hub_path": str(hub_path),
                "agents": [
                    {
                        "id": "codex",
                        "name": "Codex",
                        "skills_dir": [],
                        "mcp_config_path": str(codex_config),
                        "mcp_config_key": "mcp_servers",
                    }
                ],
            }
            service = McpService()

            result = service.add_mcp(
                config,
                {
                    "name": "playwright",
                    "type": "streamableHttp",
                    "url": "https://example.com/mcp",
                    "headers": {"Authorization": "Bearer token"},
                    "target_agents": ["codex"],
                },
            )

            self.assertTrue(result["success"])
            codex_mcps = read_agent_mcp_config(config["agents"][0])
            self.assertEqual(codex_mcps["playwright"]["http_headers"]["Authorization"], "Bearer token")

    def test_mcp_service_lists_managed_and_agent_status(self):
        from tool_hub.mcp.store import save_mcp
        from tool_hub.services.mcp import McpService

        with tempfile.TemporaryDirectory() as tmp:
            hub_path = Path(tmp) / "hub"
            hub_path.mkdir(parents=True, exist_ok=True)
            agent_config_path = Path(tmp) / "agent.json"
            agent_config_path.write_text(
                json.dumps(
                    {
                        "mcpServers": {
                            "playwright": {"command": "npx", "args": ["@playwright/mcp@latest"]}
                        }
                    }
                ),
                encoding="utf-8",
            )
            config = {
                "hub_path": str(hub_path),
                "agents": [
                    {
                        "id": "cursor",
                        "name": "Cursor",
                        "skills_dir": [],
                        "mcp_config_path": str(agent_config_path),
                        "mcp_config_key": "mcpServers",
                    }
                ],
            }
            save_mcp(
                str(hub_path),
                {
                    "name": "playwright",
                    "type": "stdio",
                    "command": "npx",
                    "args": ["@playwright/mcp@latest"],
                },
            )

            result = McpService().list_mcp(config)

            self.assertEqual(len(result["mcps"]), 1)
            self.assertTrue(result["mcps"][0]["agent_status"]["cursor"])


if __name__ == "__main__":
    unittest.main()
