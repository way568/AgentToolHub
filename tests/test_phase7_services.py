import io
import json
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest.mock import patch


def build_zip(entries):
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as zf:
        for name, content in entries.items():
            zf.writestr(name, content)
    return buffer.getvalue()


def build_multipart(filename, payload, boundary="----toolhub-boundary"):
    lines = [
        f"--{boundary}\r\n".encode("utf-8"),
        f'Content-Disposition: form-data; name="file"; filename="{filename}"\r\n'.encode("utf-8"),
        b"Content-Type: application/zip\r\n\r\n",
        payload,
        b"\r\n",
        f"--{boundary}--\r\n".encode("utf-8"),
    ]
    return b"".join(lines), boundary


class Phase7ServiceTests(unittest.TestCase):
    def setUp(self):
        self._pointer_tmp = tempfile.TemporaryDirectory()
        pointer_path = Path(self._pointer_tmp.name) / ".hub-path"
        self._hub_pointer_patcher = patch("tool_hub.config_store.HUB_PATH_POINTER", pointer_path)
        self._hub_pointer_patcher.start()

    def tearDown(self):
        self._hub_pointer_patcher.stop()
        self._pointer_tmp.cleanup()

    def test_config_service_initializes_config_and_logs(self):
        from tool_hub.audit import read_logs
        from tool_hub.config_store import load_config
        from tool_hub.services.config import ConfigService

        with tempfile.TemporaryDirectory() as tmp:
            hub_path = Path(tmp) / "hub"
            detected_agents = [
                {
                    "id": "codex",
                    "name": "Codex",
                    "skills_dir": [str(Path(tmp) / "codex-skills")],
                    "mcp_config_key": "mcp_servers",
                }
            ]

            with patch("tool_hub.services.config.detect_agents", return_value=detected_agents):
                result = ConfigService().put_config(
                    {
                        "hub_path": str(hub_path),
                        "global_exclude": ["tmp-*"],
                    }
                )

            self.assertTrue(result["initialized"])
            self.assertEqual(result["agents"][0]["id"], "codex")
            stored = load_config(str(hub_path))
            self.assertEqual(stored["global_exclude"], ["tmp-*"])
            logs = read_logs(str(hub_path))
            self.assertEqual(len(logs), 1)
            self.assertEqual(logs[0]["action"], "config")
            self.assertEqual(logs[0]["detail"]["action"], "update_config")

    def test_config_service_get_config_marks_initialized(self):
        from tool_hub.services.config import ConfigService

        result = ConfigService().get_config(
            {
                "hub_path": "/tmp/tool-hub",
                "agents": [],
                "skills": {},
            }
        )

        self.assertTrue(result["initialized"])

    def test_upload_skill_service_extracts_zip_into_hub(self):
        from tool_hub.services.upload import UploadSkillService

        with tempfile.TemporaryDirectory() as tmp:
            hub_path = Path(tmp) / "hub"
            config = {"hub_path": str(hub_path)}
            zip_payload = build_zip(
                {
                    "gamma/SKILL.md": "---\nname: gamma\ndescription: Uploaded\n---\n",
                    "gamma/scripts/run.sh": "#!/bin/sh\necho ok\n",
                }
            )
            body, boundary = build_multipart("gamma.zip", zip_payload)

            result = UploadSkillService().upload(
                config,
                {
                    "Content-Type": f'multipart/form-data; boundary="{boundary}"',
                    "Content-Length": str(len(body)),
                },
                body,
            )

            self.assertTrue(result["success"])
            self.assertEqual(result["skill"]["name"], "gamma")
            self.assertTrue((hub_path / "gamma" / "SKILL.md").exists())

    def test_upload_skill_service_rejects_escape_name(self):
        from tool_hub.errors import ToolHubError
        from tool_hub.services.upload import UploadSkillService

        with tempfile.TemporaryDirectory() as tmp:
            hub_path = Path(tmp) / "hub"
            config = {"hub_path": str(hub_path)}
            zip_payload = build_zip(
                {
                    "escape/SKILL.md": "---\nname: ../escape\ndescription: Uploaded\n---\n",
                }
            )
            body, boundary = build_multipart("escape.zip", zip_payload)

            with self.assertRaises(ToolHubError):
                UploadSkillService().upload(
                    config,
                    {
                        "Content-Type": f'multipart/form-data; boundary="{boundary}"',
                        "Content-Length": str(len(body)),
                    },
                    body,
                )

            self.assertFalse((Path(tmp) / "escape").exists())
            self.assertFalse(hub_path.exists())

    def test_upload_skill_service_rejects_non_slug_name(self):
        from tool_hub.errors import ToolHubError
        from tool_hub.services.upload import UploadSkillService

        with tempfile.TemporaryDirectory() as tmp:
            hub_path = Path(tmp) / "hub"
            config = {"hub_path": str(hub_path)}
            zip_payload = build_zip(
                {
                    "bad-name/SKILL.md": "---\nname: 中文 skill\ndescription: Uploaded\n---\n",
                }
            )
            body, boundary = build_multipart("bad.zip", zip_payload)

            with self.assertRaises(ToolHubError):
                UploadSkillService().upload(
                    config,
                    {
                        "Content-Type": f'multipart/form-data; boundary="{boundary}"',
                        "Content-Length": str(len(body)),
                    },
                    body,
                )

    def test_upload_skill_service_rejects_absolute_filename(self):
        from tool_hub.errors import ToolHubError
        from tool_hub.services.upload import UploadSkillService

        with tempfile.TemporaryDirectory() as tmp:
            hub_path = Path(tmp) / "hub"
            outside = Path(tmp) / "outside.zip"
            config = {"hub_path": str(hub_path)}
            zip_payload = build_zip(
                {
                    "gamma/SKILL.md": "---\nname: gamma\ndescription: Uploaded\n---\n",
                }
            )
            body, boundary = build_multipart(str(outside), zip_payload)

            with self.assertRaises(ToolHubError):
                UploadSkillService().upload(
                    config,
                    {
                        "Content-Type": f'multipart/form-data; boundary="{boundary}"',
                        "Content-Length": str(len(body)),
                    },
                    body,
                )

            self.assertFalse(outside.exists())

    def test_upload_skill_service_rejects_nested_filename(self):
        from tool_hub.errors import ToolHubError
        from tool_hub.services.upload import UploadSkillService

        with tempfile.TemporaryDirectory() as tmp:
            hub_path = Path(tmp) / "hub"
            config = {"hub_path": str(hub_path)}
            zip_payload = build_zip(
                {
                    "gamma/SKILL.md": "---\nname: gamma\ndescription: Uploaded\n---\n",
                }
            )
            body, boundary = build_multipart("../outside.zip", zip_payload)

            with self.assertRaises(ToolHubError):
                UploadSkillService().upload(
                    config,
                    {
                        "Content-Type": f'multipart/form-data; boundary="{boundary}"',
                        "Content-Length": str(len(body)),
                    },
                    body,
                )

    def test_mcp_service_imports_pasted_json(self):
        from tool_hub.services.mcp import McpService

        with tempfile.TemporaryDirectory() as tmp:
            hub_path = Path(tmp) / "hub"
            config = {"hub_path": str(hub_path), "agents": []}
            pasted = json.dumps({"mcpServers": {"alpha": {"command": "node", "args": ["server.js"]}}})

            result = McpService().add_mcp(config, {"config_text": pasted})

            self.assertTrue(result["success"])
            self.assertEqual(result["mcp"]["name"], "alpha")
            self.assertTrue((hub_path / "mcp" / "alpha.json").exists())

    def test_mcp_service_imports_multiple_pasted_json_servers(self):
        from tool_hub.services.mcp import McpService

        with tempfile.TemporaryDirectory() as tmp:
            hub_path = Path(tmp) / "hub"
            config = {"hub_path": str(hub_path), "agents": []}
            pasted = json.dumps(
                {
                    "mcpServers": {
                        "alpha": {"command": "node", "args": ["server.js"]},
                        "beta": {"type": "streamableHttp", "url": "http://localhost:8000"},
                    }
                }
            )

            result = McpService().add_mcp(config, {"config_text": pasted})

            self.assertEqual([item["name"] for item in result["mcps"]], ["alpha", "beta"])
            self.assertTrue((hub_path / "mcp" / "alpha.json").exists())
            self.assertTrue((hub_path / "mcp" / "beta.json").exists())

    def test_skill_service_toggle_rejects_stale_path(self):
        from tool_hub.errors import ToolHubError
        from tool_hub.services.skills import SkillService

        with tempfile.TemporaryDirectory() as tmp:
            hub_path = Path(tmp) / "hub"
            agent_dir = Path(tmp) / "cursor-skills"
            agent_dir.mkdir(parents=True, exist_ok=True)
            config = {
                "hub_path": str(hub_path),
                "skills": {
                    "ghost": {
                        "path": str(hub_path / "ghost"),
                        "agents": [],
                    }
                },
                "agents": [{"id": "cursor", "name": "Cursor", "skills_dir": [str(agent_dir)]}],
            }

            with self.assertRaises(ToolHubError):
                SkillService().toggle_skill(config, "ghost", {"agent_id": "cursor"})

            self.assertFalse((agent_dir / "ghost").exists())

    def test_skill_service_toggle_rejects_agent_without_skills_dir(self):
        from tool_hub.errors import ToolHubError
        from tool_hub.services.skills import SkillService

        with tempfile.TemporaryDirectory() as tmp:
            hub_path = Path(tmp) / "hub"
            skill_dir = hub_path / "alpha"
            skill_dir.mkdir(parents=True, exist_ok=True)
            (skill_dir / "SKILL.md").write_text("---\nname: alpha\ndescription: ok\n---\n", encoding="utf-8")
            config = {
                "hub_path": str(hub_path),
                "skills": {
                    "alpha": {
                        "path": str(skill_dir),
                        "agents": [],
                    }
                },
                "agents": [{"id": "cursor", "name": "Cursor", "skills_dir": []}],
            }

            with self.assertRaises(ToolHubError):
                SkillService().toggle_skill(config, "alpha", {"agent_id": "cursor"})

    def test_skill_service_toggle_backfills_metadata_for_discovered_skill(self):
        from tool_hub.services.skills import SkillService

        with tempfile.TemporaryDirectory() as tmp:
            hub_path = Path(tmp) / "hub"
            source_root = Path(tmp) / "codex-skills"
            target_root = Path(tmp) / "cursor-skills"
            skill_dir = source_root / "alpha"
            skill_dir.mkdir(parents=True, exist_ok=True)
            target_root.mkdir(parents=True, exist_ok=True)
            (skill_dir / "SKILL.md").write_text("---\nname: Alpha\ndescription: Backfill me\n---\n", encoding="utf-8")
            config = {
                "hub_path": str(hub_path),
                "skills": {},
                "agents": [
                    {"id": "codex", "name": "Codex", "skills_dir": [str(source_root)]},
                    {"id": "cursor", "name": "Cursor", "skills_dir": [str(target_root)]},
                ],
            }

            result = SkillService().toggle_skill(config, "alpha", {"agent_id": "cursor"})

            self.assertEqual(result["action"], "enabled")
            from tool_hub.linking import is_managed_link
            self.assertTrue(is_managed_link(target_root / "alpha"))
            self.assertEqual(config["skills"]["alpha"]["path"], str(skill_dir))
            self.assertEqual(config["skills"]["alpha"]["name"], "Alpha")
            self.assertEqual(config["skills"]["alpha"]["description"], "Backfill me")
            self.assertTrue(config["skills"]["alpha"]["source"])
            self.assertEqual(config["skills"]["alpha"]["agents"], ["cursor"])

    def test_skill_service_gather_rejects_invalid_agent_and_outside_path(self):
        from tool_hub.services.skills import SkillService

        with tempfile.TemporaryDirectory() as tmp:
            hub_path = Path(tmp) / "hub"
            source_root = Path(tmp) / "codex-skills"
            outside_root = Path(tmp) / "outside"
            source_root.mkdir(parents=True, exist_ok=True)
            outside_root.mkdir(parents=True, exist_ok=True)
            outside_skill = outside_root / "beta"
            outside_skill.mkdir(parents=True, exist_ok=True)
            (outside_skill / "SKILL.md").write_text("---\nname: beta\ndescription: Gather\n---\n", encoding="utf-8")
            config = {
                "hub_path": str(hub_path),
                "skills": {},
                "agents": [{"id": "codex", "name": "Codex", "skills_dir": [str(source_root)]}],
            }

            invalid_agent = SkillService().gather(
                config,
                {"skills": [{"name": "beta", "from": str(outside_skill), "agent_id": "../bad"}]},
            )
            missing_agent = SkillService().gather(
                config,
                {"skills": [{"name": "beta", "from": str(outside_skill), "agent_id": "cursor"}]},
            )
            outside_path = SkillService().gather(
                config,
                {"skills": [{"name": "beta", "from": str(outside_skill), "agent_id": "codex"}]},
            )
            empty_agent = SkillService().gather(
                config,
                {"skills": [{"name": "beta", "from": str(outside_skill), "agent_id": ""}]},
            )
            hub_agent = SkillService().gather(
                config,
                {"skills": [{"name": "beta", "from": str(outside_skill), "agent_id": "_hub"}]},
            )

            self.assertEqual(invalid_agent["results"][0]["status"], "error")
            self.assertEqual(missing_agent["results"][0]["status"], "error")
            self.assertEqual(outside_path["results"][0]["status"], "error")
            self.assertEqual(empty_agent["results"][0]["status"], "error")
            self.assertEqual(hub_agent["results"][0]["status"], "error")
            self.assertTrue(outside_skill.is_dir())
            self.assertFalse((hub_path / "beta").exists())

    def test_skill_service_gather_rolls_back_when_symlink_fails(self):
        from tool_hub.services.skills import SkillService

        with tempfile.TemporaryDirectory() as tmp:
            hub_path = Path(tmp) / "hub"
            source_root = Path(tmp) / "codex-skills"
            skill_dir = source_root / "beta"
            skill_dir.mkdir(parents=True, exist_ok=True)
            (skill_dir / "SKILL.md").write_text("---\nname: beta\ndescription: Gather\n---\n", encoding="utf-8")
            config = {
                "hub_path": str(hub_path),
                "skills": {},
                "agents": [{"id": "codex", "name": "Codex", "skills_dir": [str(source_root)]}],
            }

            with patch("tool_hub.services.skills.create_link", side_effect=OSError("boom")):
                result = SkillService().gather(
                    config,
                    {"skills": [{"name": "beta", "from": str(skill_dir), "agent_id": "codex"}]},
                )

            self.assertEqual(result["results"][0]["status"], "error")
            self.assertTrue(skill_dir.is_dir())
            from tool_hub.linking import is_managed_link
            self.assertFalse(is_managed_link(skill_dir))
            self.assertFalse((hub_path / "beta").exists())
            self.assertEqual(config["skills"], {})

    def test_skill_service_gather_append_log_failure_does_not_pollute_config(self):
        from tool_hub.services.skills import SkillService

        with tempfile.TemporaryDirectory() as tmp:
            hub_path = Path(tmp) / "hub"
            source_root = Path(tmp) / "codex-skills"
            skill_dir = source_root / "beta"
            skill_dir.mkdir(parents=True, exist_ok=True)
            (skill_dir / "SKILL.md").write_text("---\nname: beta\ndescription: Gather\n---\n", encoding="utf-8")
            config = {
                "hub_path": str(hub_path),
                "skills": {},
                "agents": [{"id": "codex", "name": "Codex", "skills_dir": [str(source_root)]}],
            }

            with patch("tool_hub.services.skills.append_log", side_effect=RuntimeError("log boom")):
                result = SkillService().gather(
                    config,
                    {"skills": [{"name": "beta", "from": str(skill_dir), "agent_id": "codex"}]},
                )

            self.assertEqual(result["results"][0]["status"], "error")
            self.assertTrue(skill_dir.is_dir())
            self.assertFalse((hub_path / "beta").exists())
            self.assertEqual(config["skills"], {})

    def test_skill_service_gather_rejects_name_from_basename_mismatch(self):
        from tool_hub.services.skills import SkillService

        with tempfile.TemporaryDirectory() as tmp:
            hub_path = Path(tmp) / "hub"
            source_root = Path(tmp) / "codex-skills"
            skill_dir = source_root / "alpha"
            skill_dir.mkdir(parents=True, exist_ok=True)
            (skill_dir / "SKILL.md").write_text("---\nname: alpha\ndescription: Gather\n---\n", encoding="utf-8")
            config = {
                "hub_path": str(hub_path),
                "skills": {},
                "agents": [{"id": "codex", "name": "Codex", "skills_dir": [str(source_root)]}],
            }

            result = SkillService().gather(
                config,
                {"skills": [{"name": "beta", "from": str(skill_dir), "agent_id": "codex"}]},
            )

            self.assertEqual(result["results"][0]["status"], "error")
            self.assertTrue(skill_dir.is_dir())
            self.assertFalse((hub_path / "beta").exists())
            self.assertEqual(config["skills"], {})

    def test_skill_service_gather_rejects_symlink_source(self):
        from tool_hub.services.skills import SkillService

        with tempfile.TemporaryDirectory() as tmp:
            hub_path = Path(tmp) / "hub"
            source_root = Path(tmp) / "codex-skills"
            real_root = Path(tmp) / "real-skills"
            real_skill = real_root / "beta"
            link_skill = source_root / "beta"
            real_skill.mkdir(parents=True, exist_ok=True)
            source_root.mkdir(parents=True, exist_ok=True)
            (real_skill / "SKILL.md").write_text("---\nname: beta\ndescription: Gather\n---\n", encoding="utf-8")
            from tool_hub.linking import create_link
            create_link(real_skill, link_skill)
            config = {
                "hub_path": str(hub_path),
                "skills": {},
                "agents": [{"id": "codex", "name": "Codex", "skills_dir": [str(source_root)]}],
            }

            result = SkillService().gather(
                config,
                {"skills": [{"name": "beta", "from": str(link_skill), "agent_id": "codex"}]},
            )

            self.assertEqual(result["results"][0]["status"], "error")
            from tool_hub.linking import is_managed_link
            self.assertTrue(is_managed_link(link_skill))
            self.assertTrue(real_skill.is_dir())
            self.assertFalse((hub_path / "beta").exists())

    def test_skill_service_sync_marks_missing_skills_dir_as_broken(self):
        from tool_hub.services.skills import SkillService

        with tempfile.TemporaryDirectory() as tmp:
            hub_path = Path(tmp) / "hub"
            skill_dir = hub_path / "alpha"
            skill_dir.mkdir(parents=True, exist_ok=True)
            (skill_dir / "SKILL.md").write_text("---\nname: alpha\ndescription: ok\n---\n", encoding="utf-8")
            config = {
                "hub_path": str(hub_path),
                "skills": {
                    "alpha": {
                        "path": str(skill_dir),
                        "agents": ["mcp-only"],
                    }
                },
                "agents": [{"id": "mcp-only", "name": "McpOnly", "skills_dir": []}],
            }

            result = SkillService().sync(config)

            self.assertEqual(result["report"]["created"], [])
            self.assertEqual(len(result["report"]["broken"]), 1)
            self.assertEqual(result["report"]["broken"][0]["agent"], "mcp-only")
            self.assertEqual(result["report"]["broken"][0]["reason"], "Agent 未配置 skills_dir")

    def test_skill_service_scan_sync_skips_missing_skills_dir_agent(self):
        from tool_hub.services.skills import SkillService

        with tempfile.TemporaryDirectory() as tmp:
            hub_path = Path(tmp) / "hub"
            skill_dir = hub_path / "alpha"
            skill_dir.mkdir(parents=True, exist_ok=True)
            (skill_dir / "SKILL.md").write_text("---\nname: alpha\ndescription: ok\n---\n", encoding="utf-8")
            config = {
                "hub_path": str(hub_path),
                "skills": {
                    "alpha": {
                        "path": str(skill_dir),
                        "agents": ["mcp-only"],
                    }
                },
                "agents": [{"id": "mcp-only", "name": "McpOnly", "skills_dir": []}],
            }

            result = SkillService().scan_sync(config)

            self.assertEqual(result["sync_created"], 0)
            self.assertEqual(result["sync_broken"], 1)
            self.assertEqual(result["new_discovered"], [])


if __name__ == "__main__":
    unittest.main()
