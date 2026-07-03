import re

from tool_hub.config_store import save_config
from tool_hub.errors import ToolHubError
from tool_hub.safety import validate_slug


class AgentService:
    def build_agent_from_body(self, body, fallback_id=None):
        name = body.get("name", "").strip()
        skills_dir = body.get("skills_dir", [])
        mcp_config_path = body.get("mcp_config_path", "").strip()
        raw_agent_id = body.get("id")
        if isinstance(skills_dir, str):
            skills_dir_list = [skills_dir] if skills_dir.strip() else []
        else:
            skills_dir_list = [str(path).strip() for path in skills_dir if str(path).strip()]
        if not name:
            raise ToolHubError("缺少必填字段: name")
        if not skills_dir_list and not mcp_config_path:
            raise ToolHubError("至少需要提供 skills_dir 或 mcp_config_path")
        if raw_agent_id:
            agent_id = validate_slug(raw_agent_id.lower(), label="agent_id", error_cls=ToolHubError)
        else:
            agent_id = fallback_id or re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")
            agent_id = re.sub(r"[^a-z0-9-]+", "-", agent_id.lower()).strip("-")
        if not agent_id:
            raise ToolHubError("无法生成有效 Agent ID")
        validate_slug(agent_id, label="agent_id", error_cls=ToolHubError)
        agent = {"id": agent_id, "name": name, "skills_dir": skills_dir_list}
        if mcp_config_path:
            agent["mcp_config_path"] = mcp_config_path
        agent["mcp_config_key"] = body.get("mcp_config_key", "mcpServers") or "mcpServers"
        return agent

    def add_agent(self, config, body):
        if not config:
            raise ToolHubError("系统未初始化，请先 PUT /api/config")
        new_agent = self.build_agent_from_body(body)
        for agent in config.get("agents", []):
            if agent["id"] == new_agent["id"]:
                raise ToolHubError(f"Agent ID '{new_agent['id']}' 已存在")
        config.setdefault("agents", []).append(new_agent)
        save_config(config)
        return {"ok": True, "agent": new_agent}

    def upsert_agent(self, config, body):
        if not config:
            raise ToolHubError("系统未初始化，请先 PUT /api/config")
        incoming_agent = self.build_agent_from_body(body)
        agents = config.setdefault("agents", [])
        existing_by_id_index = None
        existing_by_name_index = None
        incoming_name = incoming_agent["name"].lower()
        for index, agent in enumerate(agents):
            if agent.get("id") == incoming_agent["id"]:
                existing_by_id_index = index
            if agent.get("name", "").lower() == incoming_name:
                existing_by_name_index = index
        if (
            existing_by_id_index is not None
            and existing_by_name_index is not None
            and existing_by_id_index != existing_by_name_index
        ):
            raise ToolHubError("Agent ID 和名称分别命中了不同的现有 Agent，请手动处理冲突")
        target_index = existing_by_id_index if existing_by_id_index is not None else existing_by_name_index
        if target_index is not None:
            agents[target_index] = incoming_agent
            save_config(config)
            return {"ok": True, "action": "updated", "agent": incoming_agent}
        agents.append(incoming_agent)
        save_config(config)
        return {"ok": True, "action": "created", "agent": incoming_agent}

    def edit_agent(self, config, agent_id, body):
        if not config:
            raise ToolHubError("系统未初始化")
        validate_slug(agent_id, label="agent_id", error_cls=ToolHubError)
        for agent in config.get("agents", []):
            if agent["id"] == agent_id:
                if "name" in body:
                    agent["name"] = body["name"]
                if "skills_dir" in body:
                    skills_dir = body["skills_dir"]
                    agent["skills_dir"] = [skills_dir] if isinstance(skills_dir, str) else skills_dir
                if "mcp_config_path" in body:
                    agent["mcp_config_path"] = body["mcp_config_path"]
                if "mcp_config_key" in body:
                    agent["mcp_config_key"] = body["mcp_config_key"]
                save_config(config)
                return {"ok": True, "agent": agent}
        raise ToolHubError(f"Agent '{agent_id}' 不存在", status=404)

    def delete_agent(self, config, agent_id):
        if not config:
            raise ToolHubError("系统未初始化")
        validate_slug(agent_id, label="agent_id", error_cls=ToolHubError)
        agents = config.get("agents", [])
        new_agents = [agent for agent in agents if agent["id"] != agent_id]
        if len(new_agents) == len(agents):
            raise ToolHubError(f"Agent '{agent_id}' 不存在", status=404)
        config["agents"] = new_agents
        save_config(config)
        return {"ok": True}
