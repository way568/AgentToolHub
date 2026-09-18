import json
import tempfile
import threading
import unittest
import urllib.parse
import urllib.request
from http.server import HTTPServer
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
CN_NAME = "投资数据网-接口数据查询"


def request_json(base_url, path, method="GET", payload=None):
    headers = {}
    data = None
    if payload is not None:
        data = json.dumps(payload).encode("utf-8")
        headers["Content-Type"] = "application/json"
    req = urllib.request.Request(f"{base_url}{path}", data=data, method=method, headers=headers)
    with urllib.request.urlopen(req, timeout=5) as resp:
        return json.loads(resp.read().decode("utf-8"))


def make_skill_dir(root, name):
    skill_dir = root / name
    skill_dir.mkdir(parents=True, exist_ok=True)
    (skill_dir / "SKILL.md").write_text(
        f"---\nname: {name}\ndescription: 中文名回归测试\n---\n", encoding="utf-8"
    )
    return skill_dir


class ChineseSkillNameRegressionTests(unittest.TestCase):
    def test_validate_slug_accepts_chinese_and_rejects_dangerous(self):
        from tool_hub.errors import ToolHubError
        from tool_hub.safety import validate_slug

        self.assertEqual(validate_slug(CN_NAME, error_cls=ToolHubError), CN_NAME)
        self.assertEqual(validate_slug("dbs-save", error_cls=ToolHubError), "dbs-save")
        for bad in ("..", "a/b", "a\\b", "", "name..x", "a b"):
            with self.assertRaises(ToolHubError, msg=bad):
                validate_slug(bad, error_cls=ToolHubError)

    def test_service_gather_accepts_frontend_payload_shape(self):
        from tool_hub.linking import is_managed_link
        from tool_hub.services.skills import SkillService

        with tempfile.TemporaryDirectory() as tmp:
            hub_path = Path(tmp) / "hub"
            hub_path.mkdir(parents=True, exist_ok=True)
            source_root = Path(tmp) / "codex-skills"
            source_root.mkdir(parents=True, exist_ok=True)
            skill_dir = make_skill_dir(source_root, CN_NAME)
            config = {
                "hub_path": str(hub_path),
                "skills": {},
                "agents": [{"id": "codex", "name": "Codex", "skills_dir": [str(source_root)]}],
            }

            # 前端 scan/scan-sync 返回的条目格式：name/id/path/agent_id，无 from
            payload = {
                "skills": [{
                    "name": CN_NAME,
                    "id": CN_NAME,
                    "description": "中文名回归测试",
                    "path": str(skill_dir),
                    "agent_id": "codex",
                }]
            }
            result = SkillService().gather(config, payload)

            self.assertEqual(result["results"][0]["status"], "ok", result)
            self.assertTrue((hub_path / CN_NAME / "SKILL.md").exists())
            self.assertTrue(is_managed_link(skill_dir))
            self.assertIn(CN_NAME, config["skills"])

    def test_http_chinese_skill_gather_toggle_untoggle(self):
        from tool_hub import config_store
        from tool_hub.http_app import SkillHubHandler
        from tool_hub.linking import is_managed_link

        with tempfile.TemporaryDirectory() as tmp:
            hub_path = Path(tmp) / "hub"
            hub_path.mkdir(parents=True, exist_ok=True)
            pointer = Path(tmp) / ".hub-path"
            source_root = Path(tmp) / "codex-skills"
            target_root = Path(tmp) / "qoder-skills"
            source_root.mkdir(parents=True, exist_ok=True)
            target_root.mkdir(parents=True, exist_ok=True)
            skill_dir = make_skill_dir(source_root, CN_NAME)
            agents = [
                {"id": "codex", "name": "Codex", "skills_dir": [str(source_root)], "mcp_config_key": "mcp_servers"},
                {"id": "qoder", "name": "Qoder", "skills_dir": [str(target_root)], "mcp_config_key": "mcpServers"},
            ]

            server = HTTPServer(("127.0.0.1", 0), SkillHubHandler)
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            with patch.object(config_store, "HUB_PATH_POINTER", pointer), patch(
                "tool_hub.services.config.detect_agents", return_value=agents
            ):
                thread.start()
                try:
                    base_url = f"http://127.0.0.1:{server.server_address[1]}"
                    put = request_json(
                        base_url, "/api/config", method="PUT",
                        payload={"hub_path": str(hub_path), "global_exclude": []},
                    )
                    self.assertTrue(put["initialized"])

                    # 1. 用前端 payload 格式归聚（无 from 字段）
                    gather = request_json(
                        base_url, "/api/gather", method="POST",
                        payload={"skills": [{"name": CN_NAME, "id": CN_NAME, "path": str(skill_dir), "agent_id": "codex"}]},
                    )
                    self.assertEqual(gather["results"][0]["status"], "ok", gather)
                    self.assertTrue((hub_path / CN_NAME / "SKILL.md").exists())
                    self.assertTrue(is_managed_link(skill_dir))

                    # 2. percent-encoded 中文 id 分配给 qoder（URL 路由必须 unquote）
                    encoded = urllib.parse.quote(CN_NAME, safe="")
                    toggle = request_json(
                        base_url, f"/api/skills/{encoded}/toggle", method="POST",
                        payload={"agent_id": "qoder"},
                    )
                    self.assertTrue(toggle.get("ok"), toggle)
                    self.assertTrue(is_managed_link(target_root / CN_NAME))

                    # 3. 再次 toggle 取消分配，恢复原状
                    untoggle = request_json(
                        base_url, f"/api/skills/{encoded}/toggle", method="POST",
                        payload={"agent_id": "qoder"},
                    )
                    self.assertTrue(untoggle.get("ok"), untoggle)
                    self.assertFalse((target_root / CN_NAME).exists())
                finally:
                    server.shutdown()
                    thread.join(timeout=5)
                    server.server_close()


if __name__ == "__main__":
    unittest.main()
