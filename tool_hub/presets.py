import json
from pathlib import Path

PRESET_DIR = Path(__file__).resolve().parents[1] / "agent-presets"


def _home():
    return Path.home()


def _glob_first(pattern):
    for path in sorted(_home().glob(pattern.lstrip("~/"))):
        if path.exists():
            return str(path)
    return None


def _glob_all(pattern):
    return [str(path) for path in sorted(_home().glob(pattern.lstrip("~/"))) if path.exists()]


def _path(*parts):
    return str(_home().joinpath(*parts))


def _expand_value(value):
    if isinstance(value, str) and value.startswith("~/"):
        return str(_home() / value[2:])
    if isinstance(value, list):
        return [_expand_value(item) for item in value]
    return value


def load_agent_presets(preset_dir=None):
    directory = Path(preset_dir or PRESET_DIR)
    presets = []
    for preset_file in sorted(directory.glob("*.json")):
        with open(preset_file, "r", encoding="utf-8") as fp:
            data = json.load(fp)
        normalized = {}
        for key, value in data.items():
            normalized[key] = _expand_value(value)
        presets.append(normalized)
    return presets


def get_agent_presets():
    return load_agent_presets()


AGENT_PRESETS = get_agent_presets()


def resolve_preset_paths(preset):
    skills_dirs = []
    for candidate in preset.get("skills_dir_candidates", []):
        if Path(candidate).is_dir():
            skills_dirs.append(candidate)
    glob_pattern = preset.get("skills_dir_glob")
    if glob_pattern:
        skills_dirs.extend(_glob_all(glob_pattern))

    mcp_path = None
    for candidate in preset.get("mcp_config_candidates", []):
        if Path(candidate).is_file():
            mcp_path = candidate
            break
    if not mcp_path:
        glob_pattern = preset.get("mcp_config_glob")
        if glob_pattern:
            mcp_path = _glob_first(glob_pattern)

    return skills_dirs, mcp_path


def detect_agents():
    detected = []
    for preset in get_agent_presets():
        skills_dirs, mcp_path = resolve_preset_paths(preset)
        if not skills_dirs:
            continue
        agent = {
            "id": preset["id"],
            "name": preset["name"],
            "skills_dir": skills_dirs,
            "mcp_config_key": preset.get("mcp_config_key", "mcpServers"),
        }
        if mcp_path:
            agent["mcp_config_path"] = mcp_path
        detected.append(agent)
    return detected


def fill_missing_fields_from_preset(agent):
    preset = next((item for item in get_agent_presets() if item["id"] == agent.get("id")), None)
    if not preset:
        return False
    changed = False
    _, mcp_path = resolve_preset_paths(preset)
    if not agent.get("mcp_config_path"):
        if mcp_path:
            agent["mcp_config_path"] = mcp_path
            changed = True
    elif agent.get("id") == "claude-code" and mcp_path and agent.get("mcp_config_path") != mcp_path:
        agent["mcp_config_path"] = mcp_path
        changed = True
    if not agent.get("mcp_config_key"):
        agent["mcp_config_key"] = preset.get("mcp_config_key", "mcpServers")
        changed = True
    return changed


def migrate_config_with_presets(config):
    changed = False
    for agent in config.get("agents", []):
        if fill_missing_fields_from_preset(agent):
            changed = True
    return changed
