import json
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

from tool_hub.audit import append_log
from tool_hub.config_store import get_default_hub_path
from tool_hub.errors import ToolHubError
from tool_hub.mcp.adapters import adapt_mcp_for_agent, parse_agent_mcp_to_standard
from tool_hub.mcp.agent_config import (
    read_agent_mcp_config,
    remove_agent_mcp_entry,
    write_agent_mcp_entry,
)
from tool_hub.mcp.runtime import fetch_mcp_tools_description, test_mcp_connectivity
from tool_hub.mcp.store import delete_mcp, get_mcp_dir, load_all_mcp, save_mcp
from tool_hub.safety import validate_slug


class McpService:
    def list_mcp(self, config):
        if not config:
            return {"mcps": [], "agents": []}
        hub_path = config.get("hub_path", get_default_hub_path())
        agents = config.get("agents", [])
        managed = load_all_mcp(hub_path)
        managed_names = {mcp["name"] for mcp in managed}
        unmanaged = []
        unmanaged_map = {}
        for agent in agents:
            agent_mcps = read_agent_mcp_config(agent)
            for name, raw_cfg in agent_mcps.items():
                if name in managed_names:
                    continue
                standard = parse_agent_mcp_to_standard(name, raw_cfg, agent_id=agent["id"])
                if not standard:
                    continue
                if name in unmanaged_map:
                    unmanaged_map[name]["source_agents"].append(agent["id"])
                else:
                    standard["source"] = "agent"
                    standard["source_agents"] = [agent["id"]]
                    unmanaged_map[name] = standard
        unmanaged = list(unmanaged_map.values())
        all_mcps = managed + unmanaged
        agent_mcp_cache = {agent["id"]: read_agent_mcp_config(agent) for agent in agents}
        for mcp in all_mcps:
            mcp["agent_status"] = {}
            for agent in agents:
                mcp["agent_status"][agent["id"]] = mcp["name"] in agent_mcp_cache[agent["id"]]
        return {
            "mcps": all_mcps,
            "agents": [{"id": agent["id"], "name": agent["name"]} for agent in agents],
        }

    def gather_mcp(self, config, body):
        if not config:
            raise ToolHubError("未初始化")
        name = body.get("name", "").strip()
        source_agent_id = body.get("source_agent_id", "").strip()
        if not name or not source_agent_id:
            raise ToolHubError("缺少 name 或 source_agent_id")
        validate_slug(name, label="MCP 名称", error_cls=ToolHubError)
        validate_slug(source_agent_id, label="agent_id", error_cls=ToolHubError)
        hub_path = config.get("hub_path", get_default_hub_path())
        agents = config.get("agents", [])
        source_agent = next((agent for agent in agents if agent["id"] == source_agent_id), None)
        if not source_agent:
            raise ToolHubError(f"Agent '{source_agent_id}' 不存在", status=404)
        agent_mcps = read_agent_mcp_config(source_agent)
        raw_cfg = agent_mcps.get(name)
        if raw_cfg is None:
            raise ToolHubError(f"MCP '{name}' 在 Agent '{source_agent_id}' 中不存在", status=404)
        standard = parse_agent_mcp_to_standard(name, raw_cfg, agent_id=source_agent["id"])
        if not standard:
            raise ToolHubError("无法解析该 MCP 配置")
        standard["created_at"] = datetime.now(timezone.utc).isoformat()
        standard["gathered_from"] = source_agent_id
        save_mcp(hub_path, standard)
        batch_id = f"mcp_gather_{uuid4().hex[:8]}"
        append_log(
            hub_path,
            batch_id,
            "mcp_gather",
            name,
            {"source_agent_id": source_agent_id, "type": standard.get("type", "unknown")},
            reversible=False,
        )
        return {"success": True, "mcp": standard}

    def add_mcp(self, config, body):
        if not config:
            raise ToolHubError("未初始化")
        hub_path = config.get("hub_path", get_default_hub_path())
        mcp_data = {
            "name": body.get("name", "").strip(),
            "type": body.get("type", "stdio"),
            "description": body.get("description", ""),
            "created_at": datetime.now(timezone.utc).isoformat(),
        }
        if not mcp_data["name"]:
            raise ToolHubError("名称不能为空")
        if mcp_data["type"] == "stdio":
            mcp_data["command"] = body.get("command", "")
            mcp_data["args"] = body.get("args", [])
            if body.get("env"):
                mcp_data["env"] = body["env"]
        else:
            mcp_data["url"] = body.get("url", "")
            if body.get("headers"):
                mcp_data["headers"] = body["headers"]
        save_mcp(hub_path, mcp_data)
        target_agents = body.get("target_agents", [])
        for agent in config.get("agents", []):
            if agent["id"] in target_agents:
                adapted = adapt_mcp_for_agent(mcp_data, agent["id"])
                write_agent_mcp_entry(agent, mcp_data["name"], adapted)
        return {"success": True, "mcp": mcp_data}

    def edit_mcp(self, config, mcp_name, body):
        if not config:
            raise ToolHubError("未初始化")
        validate_slug(mcp_name, label="MCP 名称", error_cls=ToolHubError)
        hub_path = config.get("hub_path", get_default_hub_path())
        filepath = get_mcp_dir(hub_path) / f"{mcp_name}.json"
        if not filepath.exists():
            raise ToolHubError("MCP 不存在", status=404)
        with open(filepath, "r", encoding="utf-8") as fp:
            mcp_data = json.load(fp)
        for key in ["type", "description", "command", "args", "env", "url", "headers"]:
            if key in body:
                mcp_data[key] = body[key]
        save_mcp(hub_path, mcp_data)
        return {"success": True, "mcp": mcp_data}

    def delete_mcp(self, config, mcp_name):
        if not config:
            raise ToolHubError("未初始化")
        validate_slug(mcp_name, label="MCP 名称", error_cls=ToolHubError)
        hub_path = config.get("hub_path", get_default_hub_path())
        for agent in config.get("agents", []):
            remove_agent_mcp_entry(agent, mcp_name)
        deleted = delete_mcp(hub_path, mcp_name)
        if deleted:
            batch_id = f"mcp_delete_{uuid4().hex[:8]}"
            append_log(hub_path, batch_id, "mcp_delete", mcp_name, {}, reversible=False)
        return {"success": deleted}

    def toggle_mcp(self, config, mcp_name, body):
        if not config:
            raise ToolHubError("未初始化")
        validate_slug(mcp_name, label="MCP 名称", error_cls=ToolHubError)
        agent_id = body.get("agent_id", "")
        validate_slug(agent_id, label="agent_id", error_cls=ToolHubError)
        enabled = body.get("enabled", False)
        hub_path = config.get("hub_path", get_default_hub_path())
        agent = next((item for item in config.get("agents", []) if item["id"] == agent_id), None)
        if not agent:
            raise ToolHubError(f"Agent '{agent_id}' 不存在", status=404)
        if enabled:
            filepath = get_mcp_dir(hub_path) / f"{mcp_name}.json"
            if not filepath.exists():
                raise ToolHubError(f"MCP '{mcp_name}' 不存在", status=404)
            with open(filepath, "r", encoding="utf-8") as fp:
                mcp_data = json.load(fp)
            adapted = adapt_mcp_for_agent(mcp_data, agent_id)
            write_agent_mcp_entry(agent, mcp_name, adapted)
        else:
            remove_agent_mcp_entry(agent, mcp_name)
        batch_id = f"mcp_toggle_{uuid4().hex[:8]}"
        action = "mcp_enable" if enabled else "mcp_disable"
        append_log(hub_path, batch_id, action, mcp_name, {"agent_id": agent_id}, reversible=False)
        return {"success": True, "mcp_name": mcp_name, "agent_id": agent_id, "enabled": enabled}

    def test_mcp(self, config, mcp_name, fetch_tools=False):
        if not config:
            raise ToolHubError("未初始化")
        validate_slug(mcp_name, label="MCP 名称", error_cls=ToolHubError)
        hub_path = config.get("hub_path", get_default_hub_path())
        filepath = get_mcp_dir(hub_path) / f"{mcp_name}.json"
        if not filepath.exists():
            raise ToolHubError(f"MCP '{mcp_name}' 不存在", status=404)
        with open(filepath, "r", encoding="utf-8") as fp:
            mcp_data = json.load(fp)
        result = test_mcp_connectivity(mcp_data)
        if fetch_tools and result.get("status") == "ok" and not mcp_data.get("description"):
            auto_desc = fetch_mcp_tools_description(mcp_data)
            if auto_desc:
                mcp_data["description"] = auto_desc
                save_mcp(hub_path, mcp_data)
                result["auto_description"] = auto_desc
        return result
