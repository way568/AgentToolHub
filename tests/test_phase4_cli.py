import io
import json
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest.mock import patch


class Phase4CliTests(unittest.TestCase):
    def test_web_command_defaults_to_localhost(self):
        from tool_hub import cli

        with patch("tool_hub.cli.start_web_server") as start_web_server:
            cli.main(["web"])

        start_web_server.assert_called_once()
        kwargs = start_web_server.call_args.kwargs
        self.assertEqual(kwargs["host"], "127.0.0.1")

    def test_agents_list_prints_registered_agents(self):
        from tool_hub import cli

        with tempfile.TemporaryDirectory() as tmp:
            hub_path = Path(tmp) / "hub"
            hub_path.mkdir(parents=True, exist_ok=True)
            (hub_path / "tool-hub.json").write_text(
                json.dumps({"hub_path": str(hub_path), "agents": [{"id": "codex", "name": "Codex", "skills_dir": []}]}),
                encoding="utf-8",
            )

            output = io.StringIO()
            with redirect_stdout(output):
                cli.main(["agents", "list", "--hub-path", str(hub_path)])

        self.assertIn("codex", output.getvalue())
        self.assertIn("Codex", output.getvalue())

    def test_mcp_test_no_exec_disables_fetch_tools(self):
        from tool_hub import cli

        with tempfile.TemporaryDirectory() as tmp:
            hub_path = Path(tmp) / "hub"
            hub_path.mkdir(parents=True, exist_ok=True)
            mcp_dir = hub_path / "mcp"
            mcp_dir.mkdir(parents=True, exist_ok=True)
            (hub_path / "tool-hub.json").write_text(json.dumps({"hub_path": str(hub_path), "agents": []}), encoding="utf-8")
            (mcp_dir / "playwright.json").write_text(
                json.dumps({"name": "playwright", "type": "streamableHttp", "url": "https://example.com/mcp"}),
                encoding="utf-8",
            )

            with patch("tool_hub.cli.McpService.test_mcp", return_value={"status": "ok"}) as test_mcp:
                cli.main(["mcp", "test", "--hub-path", str(hub_path), "--name", "playwright", "--no-exec"])

        _, kwargs = test_mcp.call_args
        self.assertFalse(kwargs["fetch_tools"])


if __name__ == "__main__":
    unittest.main()
