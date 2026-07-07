import json
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest.mock import patch


class Phase2ServiceTests(unittest.TestCase):
    def test_http_app_config_functions_alias_config_store(self):
        from tool_hub import config_store, http_app

        self.assertIs(http_app.get_default_hub_path, config_store.get_default_hub_path)
        self.assertIs(http_app.get_saved_hub_path, config_store.get_saved_hub_path)
        self.assertIs(http_app.save_hub_path_pointer, config_store.save_hub_path_pointer)
        self.assertIs(http_app.load_config, config_store.load_config)
        self.assertIs(http_app.save_config, config_store.save_config)

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

            with patch("tool_hub.config_store.HUB_PATH_POINTER", Path(tmp) / ".hub-path"):
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

    def test_save_config_serializes_concurrent_writes(self):
        from tool_hub.config_store import load_config, save_config
        from tool_hub import config_store

        with tempfile.TemporaryDirectory() as tmp:
            hub_path = Path(tmp) / "hub"
            first = {"hub_path": str(hub_path), "agents": [{"id": "a", "name": "A", "skills_dir": []}]}
            second = {"hub_path": str(hub_path), "agents": [{"id": "b", "name": "B", "skills_dir": []}]}
            active_writers = 0
            max_active_writers = 0
            errors = []
            state_lock = threading.Lock()
            original_write = config_store._write_json_atomically

            def wrapped_write(config_path, config):
                nonlocal active_writers, max_active_writers
                with state_lock:
                    active_writers += 1
                    max_active_writers = max(max_active_writers, active_writers)
                try:
                    time.sleep(0.05)
                    return original_write(config_path, config)
                finally:
                    with state_lock:
                        active_writers -= 1

            def run_save(config):
                try:
                    save_config(config)
                except Exception as error:  # pragma: no cover
                    errors.append(error)

            with patch("tool_hub.config_store.HUB_PATH_POINTER", Path(tmp) / ".hub-path"):
                with patch("tool_hub.config_store._write_json_atomically", side_effect=wrapped_write):
                    threads = [
                        threading.Thread(target=run_save, args=(first,)),
                        threading.Thread(target=run_save, args=(second,)),
                    ]
                    for thread in threads:
                        thread.start()
                    for thread in threads:
                        thread.join()

            self.assertEqual(errors, [])
            self.assertEqual(max_active_writers, 1)
            stored = load_config(str(hub_path))
            self.assertIn(stored["agents"][0]["id"], {"a", "b"})

    def test_save_hub_path_pointer_does_not_expose_partial_content(self):
        from tool_hub.config_store import get_saved_hub_path, save_hub_path_pointer

        with tempfile.TemporaryDirectory() as tmp:
            pointer_path = Path(tmp) / ".hub-path"
            allowed = {"/tmp/hub-a", "/tmp/hub-b"}
            observed_invalid = []
            stop = threading.Event()

            def writer(value):
                for _ in range(50):
                    save_hub_path_pointer(value)
                    time.sleep(0.002)

            def reader():
                while not stop.is_set():
                    current = get_saved_hub_path()
                    if current is not None and current not in allowed:
                        observed_invalid.append(current)

            with patch("tool_hub.config_store.HUB_PATH_POINTER", pointer_path):
                save_hub_path_pointer("/tmp/hub-a")
                reader_thread = threading.Thread(target=reader)
                writers = [
                    threading.Thread(target=writer, args=("/tmp/hub-a",)),
                    threading.Thread(target=writer, args=("/tmp/hub-b",)),
                ]
                reader_thread.start()
                for thread in writers:
                    thread.start()
                for thread in writers:
                    thread.join()
                stop.set()
                reader_thread.join()
                final_value = get_saved_hub_path()

            self.assertEqual(observed_invalid, [])
            self.assertIn(final_value, allowed)


if __name__ == "__main__":
    unittest.main()
