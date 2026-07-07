import shutil
from pathlib import Path

from tool_hub.audit import read_logs, update_log_entry
from tool_hub.config_store import save_config
from tool_hub.errors import ToolHubError
from tool_hub.linking import create_link, is_managed_link, link_exists, remove_link


class AuditService:
    def list_logs(self, config, batch_id=None):
        if not config:
            return []
        return read_logs(config["hub_path"], batch_id)

    def rollback_batch(self, config, batch_id):
        if not config:
            raise ToolHubError("系统未初始化")
        hub_path = config["hub_path"]
        logs = read_logs(hub_path, batch_id)
        logs.sort(key=lambda item: item["ts"], reverse=True)
        rolled = []
        errors = []
        for entry in logs:
            if entry.get("rolled_back") or not entry.get("reversible"):
                continue
            result = self.execute_rollback(entry, config)
            if result["ok"]:
                update_log_entry(hub_path, entry["id"], {"rolled_back": True})
                rolled.append(entry["id"])
            else:
                errors.append({"id": entry["id"], "error": result["error"]})
        save_config(config)
        return {"rolled_back": rolled, "errors": errors}

    def undo_single(self, config, log_id):
        if not config:
            raise ToolHubError("系统未初始化")
        hub_path = config["hub_path"]
        logs = read_logs(hub_path)
        target = next((entry for entry in logs if entry["id"] == log_id), None)
        if not target:
            raise ToolHubError(f"日志 '{log_id}' 不存在", status=404)
        if target.get("rolled_back"):
            raise ToolHubError("该操作已回滚")
        if not target.get("reversible"):
            raise ToolHubError("该操作不可回滚")
        result = self.execute_rollback(target, config)
        if not result["ok"]:
            raise ToolHubError(result["error"])
        update_log_entry(hub_path, log_id, {"rolled_back": True})
        save_config(config)
        return {"ok": True, "rolled_back": log_id}

    def execute_rollback(self, entry, config):
        action = entry.get("action")
        detail = entry.get("detail", {})
        skill_id = entry.get("skill", "")
        skills = config.get("skills", {})

        try:
            if action == "gather":
                dest = detail.get("to", "")
                src = detail.get("from", "")
                link_at_src = Path(src)
                if is_managed_link(link_at_src):
                    remove_link(link_at_src)
                if Path(dest).exists():
                    shutil.move(dest, src)
                skills.pop(skill_id, None)
                config["skills"] = skills
            elif action == "link":
                link_path = detail.get("link_path", "")
                if is_managed_link(Path(link_path)):
                    remove_link(Path(link_path))
                agent_id = detail.get("agent_id", "")
                if skill_id in skills:
                    agent_list = skills[skill_id].get("agents", [])
                    if agent_id in agent_list:
                        agent_list.remove(agent_id)
                    skills[skill_id]["agents"] = agent_list
                    config["skills"] = skills
            elif action == "unlink":
                link_path = detail.get("link_path", "")
                target = detail.get("target", "")
                if not link_exists(Path(link_path)) and Path(target).exists():
                    Path(link_path).parent.mkdir(parents=True, exist_ok=True)
                    create_link(Path(target), Path(link_path))
                agent_id = detail.get("agent_id", "")
                if skill_id in skills:
                    agent_list = skills[skill_id].get("agents", [])
                    if agent_id not in agent_list:
                        agent_list.append(agent_id)
                    skills[skill_id]["agents"] = agent_list
                    config["skills"] = skills
            else:
                return {"ok": False, "error": f"不支持回滚 action: {action}"}
            return {"ok": True}
        except Exception as error:
            return {"ok": False, "error": str(error)}
