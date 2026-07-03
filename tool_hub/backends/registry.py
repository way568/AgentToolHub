from pathlib import Path

from tool_hub.backends.json_cfg import JsonConfigBackend
from tool_hub.backends.toml_cfg import TomlConfigBackend


BACKENDS = {
    "json": JsonConfigBackend(),
    "toml": TomlConfigBackend(),
}


def get_backend(name):
    return BACKENDS[name]


def get_backend_for_agent(agent, format_name=None):
    if format_name:
        return get_backend(format_name)
    declared = agent.get("mcp_config_format")
    if declared:
        return get_backend(declared)
    raw_path = agent.get("mcp_config_path", "")
    if isinstance(raw_path, list):
        raw_path = raw_path[0] if raw_path else ""
    suffix = Path(str(raw_path)).suffix.lower()
    if suffix == ".toml":
        return get_backend("toml")
    return get_backend("json")

