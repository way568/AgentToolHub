import json
import os
import stat
import subprocess
import sys
import tempfile
import threading
import unittest
import urllib.request
from http.server import HTTPServer
from pathlib import Path
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]


def build_zip_bytes():
    import io
    import zipfile

    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as zf:
        zf.writestr("omega/SKILL.md", "---\nname: omega\ndescription: Uploaded over HTTP\n---\n")
    return buffer.getvalue()


def build_multipart(filename, payload, boundary="----toolhub-http-boundary"):
    parts = [
        f"--{boundary}\r\n".encode("utf-8"),
        f'Content-Disposition: form-data; name="file"; filename="{filename}"\r\n'.encode("utf-8"),
        b"Content-Type: application/zip\r\n\r\n",
        payload,
        b"\r\n",
        f"--{boundary}--\r\n".encode("utf-8"),
    ]
    return b"".join(parts), boundary


class Phase7EndToEndTests(unittest.TestCase):
    def run_cli(self, *args):
        return subprocess.run(
            [sys.executable, "-m", "tool_hub.cli", *args],
            cwd=ROOT,
            capture_output=True,
            text=True,
        )

    def request_json(self, base_url, path, method="GET", payload=None, headers=None):
        headers = dict(headers or {})
        data = None
        if payload is not None and data is None and not isinstance(payload, bytes):
            data = json.dumps(payload).encode("utf-8")
            headers.setdefault("Content-Type", "application/json")
        else:
            data = payload
        req = urllib.request.Request(f"{base_url}{path}", data=data, method=method, headers=headers)
        with urllib.request.urlopen(req, timeout=5) as resp:
            return json.loads(resp.read().decode("utf-8"))

    def test_cli_agents_list_reads_real_config(self):
        with tempfile.TemporaryDirectory() as tmp:
            hub_path = Path(tmp) / "hub"
            hub_path.mkdir(parents=True, exist_ok=True)
            (hub_path / "tool-hub.json").write_text(
                json.dumps(
                    {
                        "hub_path": str(hub_path),
                        "agents": [{"id": "codex", "name": "Codex", "skills_dir": []}],
                        "skills": {},
                    }
                ),
                encoding="utf-8",
            )

            result = self.run_cli("agents", "list", "--hub-path", str(hub_path))

            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn("codex", result.stdout)
            self.assertIn("Codex", result.stdout)

    def test_cli_mcp_test_no_exec_skips_auto_description(self):
        with tempfile.TemporaryDirectory() as tmp:
            hub_path = Path(tmp) / "hub"
            mcp_dir = hub_path / "mcp"
            mcp_dir.mkdir(parents=True, exist_ok=True)
            script_path = Path(tmp) / "fake_mcp.py"
            script_path.write_text(
                "\n".join(
                    [
                        "import json, sys",
                        "for line in sys.stdin:",
                        "    msg = json.loads(line)",
                        "    method = msg.get('method')",
                        "    if method == 'initialize':",
                        "        sys.stdout.write(json.dumps({'jsonrpc': '2.0', 'id': msg.get('id'), 'result': {'capabilities': {}, 'serverInfo': {'name': 'fake', 'version': '1.0'}}}) + '\\n')",
                        "        sys.stdout.flush()",
                        "    elif method == 'tools/list':",
                        "        sys.stdout.write(json.dumps({'jsonrpc': '2.0', 'id': msg.get('id'), 'result': {'tools': [{'name': 'alpha'}, {'name': 'beta'}]}}) + '\\n')",
                        "        sys.stdout.flush()",
                    ]
                ),
                encoding="utf-8",
            )
            script_path.chmod(script_path.stat().st_mode | stat.S_IXUSR)

            (hub_path / "tool-hub.json").write_text(
                json.dumps({"hub_path": str(hub_path), "agents": [], "skills": {}}),
                encoding="utf-8",
            )
            mcp_path = mcp_dir / "fake.json"
            mcp_path.write_text(
                json.dumps(
                    {
                        "name": "fake",
                        "type": "stdio",
                        "command": sys.executable,
                        "args": [str(script_path)],
                    }
                ),
                encoding="utf-8",
            )

            first = self.run_cli("mcp", "test", "--hub-path", str(hub_path), "--name", "fake", "--no-exec")
            self.assertEqual(first.returncode, 0, first.stderr)
            self.assertIn('"status": "ok"', first.stdout)
            self.assertNotIn("description", json.loads(mcp_path.read_text(encoding="utf-8")))

            second = self.run_cli("mcp", "test", "--hub-path", str(hub_path), "--name", "fake")
            self.assertEqual(second.returncode, 0, second.stderr)
            stored = json.loads(mcp_path.read_text(encoding="utf-8"))
            self.assertEqual(stored["description"], "提供 2 个工具：alpha, beta")

    def test_cli_skills_gather_and_toggle_flow(self):
        with tempfile.TemporaryDirectory() as tmp:
            hub_path = Path(tmp) / "hub"
            source_root = Path(tmp) / "codex-skills"
            target_root = Path(tmp) / "cursor-skills"
            skill_dir = source_root / "beta"
            skill_dir.mkdir(parents=True, exist_ok=True)
            target_root.mkdir(parents=True, exist_ok=True)
            (skill_dir / "SKILL.md").write_text("---\nname: beta\ndescription: Gather Me\n---\n", encoding="utf-8")
            (hub_path / "tool-hub.json").parent.mkdir(parents=True, exist_ok=True)
            (hub_path / "tool-hub.json").write_text(
                json.dumps(
                    {
                        "hub_path": str(hub_path),
                        "skills": {},
                        "agents": [
                            {"id": "codex", "name": "Codex", "skills_dir": [str(source_root)]},
                            {"id": "cursor", "name": "Cursor", "skills_dir": [str(target_root)]},
                        ],
                    }
                ),
                encoding="utf-8",
            )

            gather = self.run_cli(
                "skills",
                "gather",
                "--hub-path",
                str(hub_path),
                "--name",
                "beta",
                "--from",
                str(skill_dir),
                "--agent-id",
                "codex",
            )
            self.assertEqual(gather.returncode, 0, gather.stderr)
            self.assertTrue((hub_path / "beta").is_dir())
            self.assertTrue(skill_dir.is_symlink())

            enable = self.run_cli(
                "skills",
                "toggle",
                "--hub-path",
                str(hub_path),
                "--skill-id",
                "beta",
                "--agent-id",
                "cursor",
            )
            self.assertEqual(enable.returncode, 0, enable.stderr)
            self.assertTrue((target_root / "beta").is_symlink())

            disable = self.run_cli(
                "skills",
                "toggle",
                "--hub-path",
                str(hub_path),
                "--skill-id",
                "beta",
                "--agent-id",
                "cursor",
            )
            self.assertEqual(disable.returncode, 0, disable.stderr)
            self.assertFalse((target_root / "beta").exists())

    def test_http_config_and_upload_flow(self):
        from tool_hub import config_store
        from tool_hub.http_app import SkillHubHandler

        with tempfile.TemporaryDirectory() as tmp:
            hub_path = Path(tmp) / "hub"
            pointer = Path(tmp) / ".hub-path"
            agent_dir = Path(tmp) / "codex-skills"
            agent_dir.mkdir(parents=True, exist_ok=True)
            server = HTTPServer(("127.0.0.1", 0), SkillHubHandler)
            thread = threading.Thread(target=server.serve_forever, daemon=True)

            with patch.object(config_store, "HUB_PATH_POINTER", pointer), patch(
                "tool_hub.services.config.detect_agents",
                return_value=[
                    {
                        "id": "codex",
                        "name": "Codex",
                        "skills_dir": [str(agent_dir)],
                        "mcp_config_key": "mcp_servers",
                    }
                ],
            ):
                thread.start()
                try:
                    base_url = f"http://127.0.0.1:{server.server_address[1]}"
                    put_result = self.request_json(
                        base_url,
                        "/api/config",
                        method="PUT",
                        payload={"hub_path": str(hub_path), "global_exclude": []},
                    )
                    self.assertTrue(put_result["initialized"])

                    agents = self.request_json(base_url, "/api/agents")
                    self.assertEqual(len(agents), 1)
                    self.assertEqual(agents[0]["id"], "codex")

                    body, boundary = build_multipart("omega.zip", build_zip_bytes())
                    upload = self.request_json(
                        base_url,
                        "/api/skills/upload",
                        method="POST",
                        payload=body,
                        headers={"Content-Type": f"multipart/form-data; boundary={boundary}"},
                    )
                    self.assertTrue(upload["success"])
                    self.assertTrue((hub_path / "omega" / "SKILL.md").exists())
                finally:
                    server.shutdown()
                    thread.join(timeout=5)
                    server.server_close()


if __name__ == "__main__":
    unittest.main()
