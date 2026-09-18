import re
import shutil
from fnmatch import fnmatch
from pathlib import Path
from uuid import uuid4

from tool_hub.audit import append_log
from tool_hub.config_store import get_default_hub_path, save_config
from tool_hub.errors import ToolHubError
from tool_hub.linking import (
    LinkError,
    create_link,
    is_managed_link,
    link_exists,
    link_points_to,
    remove_link,
    resolve_link,
    resolve_link_or_self,
)
from tool_hub.safety import resolve_child_path, validate_slug
from tool_hub.skills.backends import get_skill_backend


def normalize_skills_dirs(agent):
    skills_dir = agent.get("skills_dir", [])
    if isinstance(skills_dir, str):
        return [skills_dir]
    return skills_dir


def parse_skill_md(skill_dir):
    skill_md = Path(skill_dir) / "SKILL.md"
    if not skill_md.exists():
        return None
    content = skill_md.read_text(encoding="utf-8")
    match = re.match(r"^---\s*\n(.*?)\n---", content, re.DOTALL)
    if not match:
        return {"name": Path(skill_dir).name, "description": ""}
    frontmatter = match.group(1)
    name = ""
    description = ""
    name_match = re.search(r"^name:\s*(.+)$", frontmatter, re.MULTILINE)
    if name_match:
        name = name_match.group(1).strip().strip("'\"")
    desc_match = re.search(r"^description:\s*(.+)$", frontmatter, re.MULTILINE)
    if desc_match:
        description = desc_match.group(1).strip().strip("'\"")
    return {"name": name or Path(skill_dir).name, "description": description}


def infer_source(skill_path, hub_path, agents):
    skill_path = str(Path(skill_path).resolve())
    hub_resolved = str(Path(hub_path).resolve())
    if skill_path.startswith(hub_resolved):
        return "自研"
    for agent in agents:
        for directory in normalize_skills_dirs(agent):
            agent_dir = str(Path(directory).resolve())
            if skill_path.startswith(agent_dir) and not is_managed_link(Path(skill_path)):
                return f"{agent['name']}-内置"
    git_dir = Path(skill_path) / ".git"
    if git_dir.exists():
        git_config = git_dir / "config" if git_dir.is_dir() else None
        if git_config and git_config.exists():
            gc_content = git_config.read_text(encoding="utf-8", errors="ignore")
            remote_match = re.search(r"url\s*=\s*(.+)", gc_content)
            if remote_match:
                return remote_match.group(1).strip()
    return "未知"


def is_excluded(name, excludes):
    for pattern in excludes:
        if fnmatch(name, pattern):
            return True
    return False


class SkillService:
    def _hydrate_skill_info(self, config, skill_id, skill_info):
        hub_path = config["hub_path"]
        agents = config.get("agents", [])
        hydrated = dict(skill_info)
        skill_path = str(hydrated.get("path", "")).strip()
        resolved_path = None

        if skill_path:
            configured = Path(skill_path)
            if configured.exists():
                resolved_path = resolve_link_or_self(configured)

        if resolved_path is None:
            resolved_path = self.find_skill_real_path(skill_id, config)

        if resolved_path is not None:
            resolved_str = str(resolved_path)
            meta = parse_skill_md(resolved_str) or {}
            skill_md = resolved_path / "SKILL.md"
            hydrated["path"] = resolved_str
            hydrated["name"] = hydrated.get("name") or meta.get("name", skill_id)
            hydrated["description"] = hydrated.get("description") or meta.get("description", "")
            hydrated["source"] = hydrated.get("source") or infer_source(resolved_str, hub_path, agents)
            hydrated["mtime"] = skill_md.stat().st_mtime if skill_md.exists() else 0
        else:
            hydrated["path"] = skill_path
            hydrated["name"] = hydrated.get("name", skill_id)
            hydrated["description"] = hydrated.get("description", "")
            hydrated["source"] = hydrated.get("source", "")
            hydrated["mtime"] = 0

        return hydrated

    def list_skills(self, config):
        if not config:
            return []
        hub_path = config["hub_path"]
        managed_skills = config.get("skills", {})
        agents = config.get("agents", [])
        global_exclude = config.get("global_exclude", [])
        seen = {}

        for skill_id, skill_info in managed_skills.items():
            hydrated = self._hydrate_skill_info(config, skill_id, skill_info)
            seen[skill_id] = {
                "id": skill_id,
                "name": hydrated["name"],
                "description": hydrated["description"],
                "source": hydrated["source"],
                "path": hydrated["path"],
                "managed": True,
                "mtime": hydrated["mtime"],
            }

        for agent in agents:
            for skills_dir_str in normalize_skills_dirs(agent):
                skills_dir = Path(skills_dir_str)
                if not skills_dir.is_dir():
                    continue
                for item in skills_dir.iterdir():
                    if not item.is_dir():
                        continue
                    skill_id = item.name
                    if skill_id in seen or is_excluded(skill_id, global_exclude):
                        continue
                    real_path = resolve_link_or_self(item)
                    if not (real_path / "SKILL.md").exists():
                        continue
                    meta = parse_skill_md(str(real_path))
                    source = infer_source(str(real_path), hub_path, agents)
                    is_managed = skill_id in managed_skills or str(real_path).startswith(str(Path(hub_path).resolve()))
                    skill_md_path = real_path / "SKILL.md"
                    mtime = skill_md_path.stat().st_mtime if skill_md_path.exists() else 0
                    seen[skill_id] = {
                        "id": skill_id,
                        "name": meta.get("name", skill_id),
                        "description": meta.get("description", ""),
                        "source": source,
                        "path": str(real_path),
                        "managed": is_managed,
                        "mtime": mtime,
                    }

        seen_paths = {info.get("path") for info in seen.values() if info.get("path")}
        hub_dir = Path(hub_path)
        if hub_dir.is_dir():
            for item in hub_dir.iterdir():
                if not item.is_dir() or item.name.startswith("."):
                    continue
                skill_id = item.name
                if skill_id in seen or is_excluded(skill_id, global_exclude):
                    continue
                if not (item / "SKILL.md").exists():
                    continue
                item_resolved = str(item.resolve())
                if item_resolved in seen_paths:
                    continue
                meta = parse_skill_md(str(item))
                hub_skill_md = item / "SKILL.md"
                mtime = hub_skill_md.stat().st_mtime if hub_skill_md.exists() else 0
                seen[skill_id] = {
                    "id": skill_id,
                    "name": meta.get("name", skill_id),
                    "description": meta.get("description", ""),
                    "source": "自研",
                    "path": str(item),
                    "managed": True,
                    "mtime": mtime,
                }
                seen_paths.add(item_resolved)

        result = []
        for skill_id, info in sorted(seen.items()):
            skill_cfg = managed_skills.get(skill_id, {})
            origin_agent_id = skill_cfg.get("origin_agent")
            agent_status = {}
            for agent in agents:
                status = False
                for directory in normalize_skills_dirs(agent):
                    link_path = Path(directory) / skill_id
                    if is_managed_link(link_path):
                        status = "linked"
                        break
                    if link_path.is_dir():
                        status = "origin"
                        break
                if origin_agent_id == agent["id"] and status in ("linked",):
                    status = "origin"
                if status == "origin" and not origin_agent_id:
                    origin_agent_id = agent["id"]
                agent_status[agent["id"]] = status
            info["agents"] = agent_status
            info["origin_agent"] = origin_agent_id
            result.append(info)
        return result

    def find_skill_real_path(self, skill_id, config):
        validate_slug(skill_id, label="skill_id", error_cls=ToolHubError)
        skills = config.get("skills", {})
        if skill_id in skills and skills[skill_id].get("path"):
            configured = Path(skills[skill_id]["path"])
            if configured.exists():
                return configured
        for agent in config.get("agents", []):
            for directory in normalize_skills_dirs(agent):
                candidate = Path(directory) / skill_id
                if candidate.exists():
                    return resolve_link_or_self(candidate)
        hub_candidate = Path(config["hub_path"]) / skill_id
        if hub_candidate.exists():
            return hub_candidate
        return None

    def toggle_skill(self, config, skill_id, body):
        if not config:
            raise ToolHubError("系统未初始化")
        validate_slug(skill_id, label="skill_id", error_cls=ToolHubError)
        agent_id = body.get("agent_id", "")
        validate_slug(agent_id, label="agent_id", error_cls=ToolHubError)
        hub_path = config["hub_path"]
        agents = config.get("agents", [])
        target_agent = next((agent for agent in agents if agent["id"] == agent_id), None)
        if not target_agent:
            raise ToolHubError(f"Agent '{agent_id}' 不存在")
        skill_real_path = self.find_skill_real_path(skill_id, config)
        if not skill_real_path:
            raise ToolHubError(f"Skill '{skill_id}' 不存在")

        agent_dirs = normalize_skills_dirs(target_agent)
        if not agent_dirs:
            raise ToolHubError(f"Agent '{agent_id}' 未配置 skills_dir")
        existing_link_path = None
        existing_is_link = False
        existing_is_dir = False
        for directory in agent_dirs:
            candidate = Path(directory) / skill_id
            if is_managed_link(candidate):
                existing_link_path = candidate
                existing_is_link = True
                break
            if candidate.is_dir():
                existing_link_path = candidate
                existing_is_dir = True
                break

        batch_id = f"toggle_{uuid4().hex[:8]}"
        skill_cfg = config.setdefault("skills", {}).setdefault(skill_id, {})
        meta = parse_skill_md(str(skill_real_path)) or {}
        if not skill_cfg.get("path"):
            skill_cfg["path"] = str(skill_real_path)
        if not skill_cfg.get("name"):
            skill_cfg["name"] = meta.get("name", skill_id)
        if not skill_cfg.get("description"):
            skill_cfg["description"] = meta.get("description", "")
        if not skill_cfg.get("source"):
            skill_cfg["source"] = infer_source(str(skill_real_path), hub_path, agents)
        enabled_agents = skill_cfg.setdefault("agents", [])

        if existing_is_link:
            remove_link(existing_link_path)
            if agent_id in enabled_agents:
                enabled_agents.remove(agent_id)
            append_log(hub_path, batch_id, "unlink", skill_id, {
                "agent_id": agent_id,
                "link_path": str(existing_link_path),
                "target": str(skill_real_path),
            })
            save_config(config)
            return {"ok": True, "action": "disabled", "skill_id": skill_id, "agent_id": agent_id}

        if existing_is_dir:
            hub_dest = Path(hub_path) / skill_id
            if hub_dest.exists():
                raise ToolHubError(f"中央仓库已存在 '{skill_id}'，无法移入")
            shutil.move(str(existing_link_path), str(hub_dest))
            skill_cfg["origin_agent"] = agent_id
            skill_cfg["path"] = str(hub_dest)
            if not skill_cfg.get("source"):
                skill_cfg["source"] = "自研"
            if agent_id in enabled_agents:
                enabled_agents.remove(agent_id)
            save_config(config)
            append_log(hub_path, batch_id, "unlink_origin", skill_id, {
                "agent_id": agent_id,
                "from_path": str(existing_link_path),
                "to_path": str(hub_dest),
            })
            return {"ok": True, "action": "disabled", "skill_id": skill_id, "agent_id": agent_id}

        link_path = Path(agent_dirs[0]) / skill_id
        link_path.parent.mkdir(parents=True, exist_ok=True)
        create_link(skill_real_path, link_path)
        if agent_id not in enabled_agents:
            enabled_agents.append(agent_id)
        save_config(config)
        append_log(hub_path, batch_id, "link", skill_id, {
            "agent_id": agent_id,
            "link_path": str(link_path),
            "target": str(skill_real_path),
        })
        return {"ok": True, "action": "enabled", "skill_id": skill_id, "agent_id": agent_id}

    def scan(self, config):
        if not config:
            raise ToolHubError("系统未初始化")
        hub_path = config["hub_path"]
        agents = config.get("agents", [])
        skills = config.get("skills", {})
        global_exclude = config.get("global_exclude", [])
        report = {"already_managed": [], "new_discovered": [], "skipped": []}

        for agent in agents:
            for skills_dir_str in normalize_skills_dirs(agent):
                skills_dir = Path(skills_dir_str)
                if not skills_dir.is_dir():
                    continue
                for item in skills_dir.iterdir():
                    if not item.is_dir():
                        continue
                    skill_name = item.name
                    if is_managed_link(item):
                        report["skipped"].append({"name": skill_name, "reason": "symlink", "agent": agent["id"]})
                        continue
                    if is_excluded(skill_name, global_exclude):
                        report["skipped"].append({"name": skill_name, "reason": "excluded", "agent": agent["id"]})
                        continue
                    if not (item / "SKILL.md").exists():
                        report["skipped"].append({"name": skill_name, "reason": "no SKILL.md", "agent": agent["id"]})
                        continue
                    meta = parse_skill_md(str(item))
                    if skill_name in skills:
                        report["already_managed"].append({
                            "name": meta.get("name", skill_name),
                            "id": skill_name,
                            "path": str(item),
                            "agent": agent["id"],
                        })
                    else:
                        report["new_discovered"].append({
                            "name": meta.get("name", skill_name),
                            "id": skill_name,
                            "description": meta.get("description", ""),
                            "path": str(item),
                            "agent_id": agent["id"],
                            "agent_name": agent["name"],
                            "source": infer_source(str(item), hub_path, agents),
                        })

        hub_dir = Path(hub_path)
        if hub_dir.is_dir():
            for item in hub_dir.iterdir():
                if not item.is_dir() or item.name.startswith("."):
                    continue
                if not (item / "SKILL.md").exists():
                    continue
                skill_name = item.name
                if skill_name in skills or is_excluded(skill_name, global_exclude):
                    continue
                meta = parse_skill_md(str(item))
                report["new_discovered"].append({
                    "name": meta.get("name", skill_name),
                    "id": skill_name,
                    "description": meta.get("description", ""),
                    "path": str(item),
                    "agent_id": "_hub",
                    "agent_name": "中央仓库",
                    "source": "自研",
                })
        return report

    def gather(self, config, body):
        if not config:
            raise ToolHubError("系统未初始化")
        skill_list = body.get("skills", [])
        if not skill_list:
            raise ToolHubError("缺少 skills 列表")
        hub_path = config["hub_path"]
        agents = config.get("agents", [])
        skills = config.get("skills", {})
        batch_id = f"gather_{uuid4().hex[:8]}"
        results = []

        for item in skill_list:
            skill_name = item.get("id") or item.get("name", "")
            from_path = item.get("from") or item.get("path", "")
            agent_id = str(item.get("agent_id", "")).strip()
            if not skill_name or not from_path:
                results.append({"name": skill_name, "status": "error", "message": "缺少 name 或 from"})
                continue

            moved = False
            link_created = False
            src = Path(from_path)
            dest = None
            try:
                validate_slug(skill_name, label="skill_id", error_cls=ToolHubError)
                validate_slug(agent_id, label="agent_id", error_cls=ToolHubError)
                target_agent = next((agent for agent in agents if agent["id"] == agent_id), None)
                if not target_agent:
                    raise ToolHubError(f"Agent '{agent_id}' 不存在")
                agent_dirs = normalize_skills_dirs(target_agent)
                if not agent_dirs:
                    raise ToolHubError(f"Agent '{agent_id}' 未配置 skills_dir")
                src_resolved = src.resolve()
                allowed = False
                for directory in agent_dirs:
                    try:
                        src_resolved.relative_to(Path(directory).expanduser().resolve())
                        allowed = True
                        break
                    except ValueError:
                        continue
                if not allowed:
                    raise ToolHubError(f"源路径不属于 Agent '{agent_id}' 的 skills_dir")
                dest = resolve_child_path(hub_path, skill_name, label="skill_id", error_cls=ToolHubError)
                if not src.exists():
                    raise ToolHubError(f"源路径不存在: {from_path}")
                if is_managed_link(src):
                    raise ToolHubError("源路径不能是 managed link")
                if src.name != skill_name:
                    raise ToolHubError(f"源路径名称与 skill_id 不一致: {src.name} != {skill_name}")
                if dest.exists():
                    raise ToolHubError(f"目标已存在: {dest}")

                shutil.move(str(src), str(dest))
                moved = True
                create_link(dest, src)
                link_created = True
                meta = parse_skill_md(str(dest))
                if not meta:
                    raise ToolHubError("缺少 SKILL.md 文件")
                source = infer_source(str(dest), hub_path, agents)
                skill_entry = {
                    "name": meta.get("name", skill_name),
                    "description": meta.get("description", ""),
                    "path": str(dest),
                    "source": source,
                    "agents": [agent_id],
                }
                append_log(hub_path, batch_id, "gather", skill_name, {
                    "from": from_path,
                    "to": str(dest),
                    "agent_id": agent_id,
                    "link_created": str(src),
                })
                skills[skill_name] = skill_entry
                results.append({"name": skill_name, "status": "ok"})
            except Exception as error:
                rollback_error = None
                try:
                    if link_created and is_managed_link(src):
                        remove_link(src)
                    if moved and dest and dest.exists() and not src.exists():
                        shutil.move(str(dest), str(src))
                except Exception as rollback_exc:
                    rollback_error = str(rollback_exc)
                message = str(error)
                if rollback_error:
                    message = f"{message}; 回滚失败: {rollback_error}"
                results.append({"name": skill_name, "status": "error", "message": str(error)})
                if rollback_error:
                    results[-1]["message"] = message

        config["skills"] = skills
        save_config(config)
        return {"batch_id": batch_id, "results": results}

    def sync(self, config):
        if not config:
            raise ToolHubError("系统未初始化")
        hub_path = config["hub_path"]
        agents = config.get("agents", [])
        skills = config.get("skills", {})
        batch_id = f"sync_{uuid4().hex[:8]}"
        report = {"created": [], "orphaned": [], "broken": []}

        for skill_id, skill_info in skills.items():
            skill_path = self.find_skill_real_path(skill_id, config)
            enabled_agents = skill_info.get("agents", [])
            if not skill_path or not skill_path.exists():
                report["broken"].append({"skill": skill_id, "path": skill_info.get("path", ""), "reason": "skill目录不存在"})
                continue
            for agent in agents:
                agent_dirs = normalize_skills_dirs(agent)
                should_exist = agent["id"] in enabled_agents
                if should_exist:
                    if not agent_dirs:
                        report["broken"].append({
                            "skill": skill_id,
                            "agent": agent["id"],
                            "reason": "Agent 未配置 skills_dir",
                        })
                        continue
                    exists_anywhere = any(link_exists(Path(directory) / skill_id) for directory in agent_dirs)
                    if not exists_anywhere:
                        link_path = Path(agent_dirs[0]) / skill_id
                        link_path.parent.mkdir(parents=True, exist_ok=True)
                        create_link(skill_path, link_path)
                        append_log(hub_path, batch_id, "link", skill_id, {
                            "agent_id": agent["id"],
                            "link_path": str(link_path),
                            "target": str(skill_path),
                            "reason": "sync_create",
                        })
                        report["created"].append({"skill": skill_id, "agent": agent["id"], "link": str(link_path)})
                else:
                    for directory in agent_dirs:
                        link_path = Path(directory) / skill_id
                        if link_points_to(link_path, skill_path):
                            report["orphaned"].append({"skill": skill_id, "agent": agent["id"], "link": str(link_path)})
                for directory in agent_dirs:
                    link_path = Path(directory) / skill_id
                    if is_managed_link(link_path) and not resolve_link(link_path).exists():
                        report["broken"].append({"skill": skill_id, "agent": agent["id"], "link": str(link_path), "reason": "断链"})
        return {"batch_id": batch_id, "report": report}

    def scan_sync(self, config):
        if not config:
            raise ToolHubError("系统未初始化")
        hub_path = config["hub_path"]
        agents = config.get("agents", [])
        skills = config.get("skills", {})
        sync_created = 0
        sync_broken = 0
        for skill_id, skill_info in skills.items():
            skill_path = self.find_skill_real_path(skill_id, config)
            if not skill_path or not skill_path.exists():
                sync_broken += 1
                continue
            for agent in agents:
                agent_dirs = normalize_skills_dirs(agent)
                agent_enabled = agent["id"] in skill_info.get("agents", [])
                if agent_enabled:
                    if not agent_dirs:
                        sync_broken += 1
                        continue
                    exists_anywhere = any(link_exists(Path(directory) / skill_id) for directory in agent_dirs)
                    if not exists_anywhere:
                        link_path = Path(agent_dirs[0]) / skill_id
                        link_path.parent.mkdir(parents=True, exist_ok=True)
                        create_link(skill_path, link_path)
                        sync_created += 1

        global_exclude = config.get("global_exclude", [])
        new_discovered = []
        seen_names = set(skills.keys())
        hub_dir = Path(hub_path)
        if hub_dir.is_dir():
            for item in hub_dir.iterdir():
                if item.is_dir():
                    seen_names.add(item.name)
        for agent in agents:
            for skills_dir_str in normalize_skills_dirs(agent):
                skills_dir = Path(skills_dir_str)
                if not skills_dir.is_dir():
                    continue
                for item in skills_dir.iterdir():
                    if item.is_dir():
                        seen_names.add(item.name)
        for agent in agents:
            for skills_dir_str in normalize_skills_dirs(agent):
                skills_dir = Path(skills_dir_str)
                if not skills_dir.is_dir():
                    continue
                for item in skills_dir.iterdir():
                    if not item.is_dir() or is_managed_link(item):
                        continue
                    skill_name = item.name
                    if skill_name in seen_names or is_excluded(skill_name, global_exclude):
                        continue
                    if not (item / "SKILL.md").exists():
                        continue
                    seen_names.add(skill_name)
                    meta = parse_skill_md(str(item))
                    new_discovered.append({
                        "name": meta.get("name", skill_name),
                        "id": skill_name,
                        "description": meta.get("description", ""),
                        "path": str(item),
                        "agent_id": agent["id"],
                        "agent_name": agent["name"],
                        "source": infer_source(str(item), hub_path, agents),
                    })
        return {
            "new_discovered": new_discovered,
            "sync_created": sync_created,
            "sync_broken": sync_broken,
        }

    def delete_skill(self, config, skill_id):
        if not config:
            raise ToolHubError("未初始化")
        validate_slug(skill_id, label="skill_id", error_cls=ToolHubError)
        hub_path = config.get("hub_path", get_default_hub_path())
        backend_name = config.get("skill_backend", "directory_symlink")
        backend = get_skill_backend(backend_name)
        managed_skills = config.get("skills", {})
        skill_registered = skill_id in managed_skills

        for agent in config.get("agents", []):
            for directory in normalize_skills_dirs(agent):
                link_path = Path(directory) / skill_id
                if not is_managed_link(link_path):
                    continue
                try:
                    remove_link(link_path)
                except LinkError as error:
                    raise ToolHubError(str(error))

        try:
            result = backend.delete(hub_path, skill_id, ToolHubError)
        except ToolHubError as error:
            if error.status != 404 or not skill_registered:
                raise
            result = {"success": True, "already_missing": True}

        managed_skills.pop(skill_id, None)
        config["skills"] = managed_skills
        save_config(config)
        return result
