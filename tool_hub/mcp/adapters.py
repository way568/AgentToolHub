import json
from pathlib import Path


MCP_ADAPTERS_DIR = Path(__file__).resolve().parents[1] / "data" / "mcp-adapters"
DEFAULT_TYPE_ALIASES = {
    "http": "streamableHttp",
    "streamable-http": "streamableHttp",
    "streamableHttp": "streamableHttp",
    "sse": "sse",
    "stdio": "stdio",
}


def normalize_mcp_type(mcp_type):
    return DEFAULT_TYPE_ALIASES.get(mcp_type, mcp_type)


def resolve_mcp_adapter_id(agent):
    if isinstance(agent, str):
        return agent
    if not isinstance(agent, dict):
        return ""
    if agent.get("id") == "qoder":
        raw_paths = agent.get("mcp_config_path", "")
        paths = raw_paths if isinstance(raw_paths, list) else [raw_paths]
        for path in paths:
            parts = Path(path).expanduser().parts if path else ()
            if len(parts) >= 2 and parts[-2:] == (".qoder", "settings.json"):
                return "qodercli"
    return agent.get("id", "")


def load_adapter(agent_id):
    adapter_file = MCP_ADAPTERS_DIR / f"{agent_id}.json"
    if adapter_file.exists():
        with open(adapter_file, "r", encoding="utf-8") as fp:
            return json.load(fp)
    return None


def parse_agent_mcp_to_standard(name, raw_config, agent_id=None):
    if not isinstance(raw_config, dict):
        return None
    adapter_id = resolve_mcp_adapter_id(agent_id)
    adapter = load_adapter(adapter_id) if adapter_id else None
    read_mapping = adapter.get("read_mapping", {}) if adapter else {}
    headers_fields = read_mapping.get("headers_fields", ["headers", "http_headers"])
    type_aliases = dict(DEFAULT_TYPE_ALIASES)
    type_aliases.update(read_mapping.get("type_aliases", {}))
    standard = {"name": name, "description": raw_config.get("description", "")}
    if "command" in raw_config:
        standard["type"] = "stdio"
        standard["command"] = raw_config.get("command", "")
        standard["args"] = raw_config.get("args", []) or []
        if raw_config.get("env"):
            standard["env"] = raw_config["env"]
    elif "url" in raw_config:
        raw_type = raw_config.get("type")
        url = raw_config.get("url", "")
        if raw_type == "sse" or (raw_type is None and "/sse" in url):
            standard["type"] = "sse"
        elif raw_type is None:
            standard["type"] = "streamableHttp"
        else:
            standard["type"] = type_aliases.get(raw_type, raw_type)
        standard["url"] = raw_config["url"]
    else:
        standard["type"] = "unknown"
    for field in headers_fields:
        if raw_config.get(field):
            standard["headers"] = raw_config[field]
            break
    return standard


def build_raw_config(mcp_data):
    mcp_type = normalize_mcp_type(mcp_data.get("type", "stdio"))
    result = {}
    if mcp_type == "stdio":
        result["command"] = mcp_data.get("command", "")
        result["args"] = mcp_data.get("args", [])
        if mcp_data.get("env"):
            result["env"] = mcp_data["env"]
    else:
        result["type"] = mcp_type
        result["url"] = mcp_data.get("url", "")
        if mcp_data.get("headers"):
            result["headers"] = mcp_data["headers"]
    return result


def adapt_mcp_for_agent(mcp_data, agent_id):
    adapter = load_adapter(resolve_mcp_adapter_id(agent_id))
    mcp_type = normalize_mcp_type(mcp_data.get("type", "stdio"))
    if adapter is None:
        return build_raw_config(mcp_data)
    mapping_root = adapter.get("write_mapping") or adapter.get("type_mapping", {})
    mapping = mapping_root.get(mcp_type)
    if mapping is None:
        return build_raw_config(mcp_data)
    result = {}
    transform = mapping.get("transform", "")
    if mcp_type == "stdio":
        result["command"] = mcp_data.get("command", "")
        result["args"] = mcp_data.get("args", [])
        if mcp_data.get("env"):
            result["env"] = mcp_data["env"]
    else:
        if transform != "no_type_field":
            result["type"] = mapping.get("type_field_value", mcp_type)
        result["url"] = mcp_data.get("url", "")
        if mcp_data.get("headers"):
            result[mapping.get("headers_field", "headers")] = mcp_data["headers"]
    return result
