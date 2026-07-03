import json
from pathlib import Path

from tool_hub.backends.registry import get_backend_for_agent
from tool_hub.mcp.adapters import load_adapter


def get_mcp_config_paths(agent):
    raw = agent.get("mcp_config_path", "")
    if not raw:
        return []
    if isinstance(raw, list):
        return [Path(path).expanduser() for path in raw if path]
    return [Path(raw).expanduser()]


def read_agent_mcp_config(agent):
    config_key = agent.get("mcp_config_key", "mcpServers")
    adapter = load_adapter(agent.get("id", ""))
    format_name = adapter.get("config_format") if adapter else None
    backend = get_backend_for_agent(agent, format_name=format_name)
    merged = {}
    for config_path in get_mcp_config_paths(agent):
        if not config_path.is_file():
            continue
        try:
            servers = backend.read_servers(config_path, config_key)
            if isinstance(servers, dict):
                merged.update(servers)
        except (json.JSONDecodeError, IOError, OSError):
            continue
    return merged


def write_agent_mcp_entry(agent, mcp_name, mcp_config):
    config_key = agent.get("mcp_config_key", "mcpServers")
    adapter = load_adapter(agent.get("id", ""))
    format_name = adapter.get("config_format") if adapter else None
    backend = get_backend_for_agent(agent, format_name=format_name)
    for config_path in get_mcp_config_paths(agent):
        if not config_path.is_file():
            continue
        backend.write_server(config_path, config_key, mcp_name, mcp_config)
        return True
    return False


def remove_agent_mcp_entry(agent, mcp_name):
    config_key = agent.get("mcp_config_key", "mcpServers")
    adapter = load_adapter(agent.get("id", ""))
    format_name = adapter.get("config_format") if adapter else None
    backend = get_backend_for_agent(agent, format_name=format_name)
    removed = False
    for config_path in get_mcp_config_paths(agent):
        if not config_path.is_file():
            continue
        _, current_removed = backend.remove_server(config_path, config_key, mcp_name)
        removed = current_removed or removed
    return removed
