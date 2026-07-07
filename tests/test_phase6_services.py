import json
import os
import tempfile
import unittest
from pathlib import Path


class Phase6ServiceTests(unittest.TestCase):
    def test_skill_service_lists_managed_and_agent_status(self):
        from tool_hub.services.skills import SkillService

        with tempfile.TemporaryDirectory() as tmp:
            hub_path = Path(tmp) / "hub"
            hub_skill = hub_path / "alpha"
            hub_skill.mkdir(parents=True, exist_ok=True)
            (hub_skill / "SKILL.md").write_text("---\nname: Alpha\ndescription: Managed\n---\n", encoding="utf-8")

            agent_dir = Path(tmp) / "agent-skills"
            agent_dir.mkdir(parents=True, exist_ok=True)
            from tool_hub.linking import create_link
            create_link(hub_skill, agent_dir / "alpha")

            config = {
                "hub_path": str(hub_path),
                "skills": {
                    "alpha": {
                        "name": "Alpha",
                        "description": "Managed",
                        "path": str(hub_skill),
                        "source": "自研",
                    }
                },
                "agents": [{"id": "codex", "name": "Codex", "skills_dir": [str(agent_dir)]}],
                "global_exclude": [],
            }

            result = SkillService().list_skills(config)

            self.assertEqual(len(result), 1)
            self.assertEqual(result[0]["id"], "alpha")
            self.assertEqual(result[0]["agents"]["codex"], "linked")

    def test_skill_service_lists_managed_skill_with_missing_path_from_agent_symlink(self):
        from tool_hub.services.skills import SkillService

        with tempfile.TemporaryDirectory() as tmp:
            hub_path = Path(tmp) / "hub"
            real_root = Path(tmp) / "source-skills"
            real_skill = real_root / "alpha"
            real_skill.mkdir(parents=True, exist_ok=True)
            (real_skill / "SKILL.md").write_text("---\nname: Alpha\ndescription: Restored\n---\n", encoding="utf-8")

            agent_dir = Path(tmp) / "agent-skills"
            agent_dir.mkdir(parents=True, exist_ok=True)
            from tool_hub.linking import create_link
            create_link(real_skill, agent_dir / "alpha")

            config = {
                "hub_path": str(hub_path),
                "skills": {
                    "alpha": {
                        "agents": ["codex"],
                    }
                },
                "agents": [{"id": "codex", "name": "Codex", "skills_dir": [str(agent_dir)]}],
                "global_exclude": [],
            }

            result = SkillService().list_skills(config)

            self.assertEqual(len(result), 1)
            self.assertEqual(Path(result[0]["path"]).resolve(), real_skill.resolve())
            self.assertEqual(result[0]["name"], "Alpha")
            self.assertEqual(result[0]["description"], "Restored")
            self.assertEqual(result[0]["agents"]["codex"], "linked")

    def test_skill_service_gather_moves_and_links(self):
        from tool_hub.services.skills import SkillService

        with tempfile.TemporaryDirectory() as tmp:
            hub_path = Path(tmp) / "hub"
            src_root = Path(tmp) / "codex-skills"
            src_skill = src_root / "beta"
            src_skill.mkdir(parents=True, exist_ok=True)
            (src_skill / "SKILL.md").write_text("---\nname: Beta\ndescription: Gathered\n---\n", encoding="utf-8")
            config = {
                "hub_path": str(hub_path),
                "skills": {},
                "agents": [{"id": "codex", "name": "Codex", "skills_dir": [str(src_root)]}],
            }

            result = SkillService().gather(
                config,
                {
                    "skills": [
                        {"name": "beta", "from": str(src_skill), "agent_id": "codex"}
                    ]
                },
            )

            self.assertEqual(result["results"][0]["status"], "ok")
            self.assertTrue((hub_path / "beta").is_dir())
            from tool_hub.linking import is_managed_link
            self.assertTrue(is_managed_link(src_root / "beta"))

    def test_skill_service_delete_removes_hub_registry_and_agent_link(self):
        from tool_hub.linking import create_link
        from tool_hub.services.skills import SkillService

        with tempfile.TemporaryDirectory() as tmp:
            hub_path = Path(tmp) / "hub"
            hub_skill = hub_path / "alpha"
            hub_skill.mkdir(parents=True, exist_ok=True)
            (hub_skill / "SKILL.md").write_text("---\nname: Alpha\n---\n", encoding="utf-8")
            agent_dir = Path(tmp) / "agent-skills"
            agent_dir.mkdir(parents=True, exist_ok=True)
            agent_link = agent_dir / "alpha"
            create_link(hub_skill, agent_link)
            config = {
                "hub_path": str(hub_path),
                "skills": {
                    "alpha": {
                        "name": "Alpha",
                        "path": str(hub_skill),
                        "agents": ["codex"],
                    }
                },
                "agents": [{"id": "codex", "name": "Codex", "skills_dir": [str(agent_dir)]}],
            }

            result = SkillService().delete_skill(config, "alpha")

            self.assertTrue(result["success"])
            self.assertFalse(hub_skill.exists())
            self.assertFalse(os.path.lexists(agent_link))
            self.assertNotIn("alpha", config["skills"])
            persisted = json.loads((hub_path / "tool-hub.json").read_text(encoding="utf-8"))
            self.assertNotIn("alpha", persisted["skills"])

    def test_skill_service_delete_clears_registered_skill_when_hub_dir_missing(self):
        from tool_hub.linking import create_link
        from tool_hub.services.skills import SkillService

        with tempfile.TemporaryDirectory() as tmp:
            hub_path = Path(tmp) / "hub"
            hub_skill = hub_path / "ghost"
            hub_skill.mkdir(parents=True, exist_ok=True)
            (hub_skill / "SKILL.md").write_text("---\nname: Ghost\n---\n", encoding="utf-8")
            agent_dir = Path(tmp) / "agent-skills"
            agent_dir.mkdir(parents=True, exist_ok=True)
            agent_link = agent_dir / "ghost"
            create_link(hub_skill, agent_link)
            import shutil
            shutil.rmtree(hub_skill)
            config = {
                "hub_path": str(hub_path),
                "skills": {
                    "ghost": {
                        "name": "Ghost",
                        "path": str(hub_skill),
                        "agents": ["codex"],
                    }
                },
                "agents": [{"id": "codex", "name": "Codex", "skills_dir": [str(agent_dir)]}],
            }

            result = SkillService().delete_skill(config, "ghost")

            self.assertTrue(result["success"])
            self.assertTrue(result["already_missing"])
            self.assertFalse(os.path.lexists(agent_link))
            self.assertNotIn("ghost", config["skills"])

    def test_audit_service_lists_logs_by_batch(self):
        from tool_hub.audit import append_log
        from tool_hub.services.audit import AuditService

        with tempfile.TemporaryDirectory() as tmp:
            append_log(tmp, "batch-1", "gather", "alpha", {"from": "/tmp/a"})
            append_log(tmp, "batch-2", "link", "beta", {"from": "/tmp/b"})

            result = AuditService().list_logs({"hub_path": tmp}, batch_id="batch-1")

            self.assertEqual(len(result), 1)
            self.assertEqual(result[0]["batch_id"], "batch-1")


if __name__ == "__main__":
    unittest.main()
