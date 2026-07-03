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
            (agent_dir / "alpha").symlink_to(hub_skill)

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
            self.assertTrue((src_root / "beta").is_symlink())

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
