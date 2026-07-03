import shutil

from tool_hub.safety import resolve_child_path


class DirectorySymlinkSkillBackend:
    name = "directory_symlink"

    def delete(self, hub_path, skill_id, error_cls):
        skill_dir = resolve_child_path(hub_path, skill_id, label="skill_id", error_cls=error_cls)
        if not skill_dir.exists():
            raise error_cls(f"Skill '{skill_id}' 不存在", status=404)
        shutil.rmtree(skill_dir)
        return {"success": True}


SKILL_BACKENDS = {
    "directory_symlink": DirectorySymlinkSkillBackend(),
}


def get_skill_backend(name="directory_symlink"):
    return SKILL_BACKENDS[name]
