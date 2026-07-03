import json
from pathlib import Path

MCP_DIR_NAME = "mcp"
from tool_hub.safety import make_backup, validate_slug


def validate_mcp_name(name):
    return validate_slug(name, label="MCP 名称")


def get_mcp_dir(hub_path):
    mcp_dir = Path(hub_path) / MCP_DIR_NAME
    mcp_dir.mkdir(parents=True, exist_ok=True)
    return mcp_dir


def load_all_mcp(hub_path):
    mcp_dir = get_mcp_dir(hub_path)
    result = []
    for item in sorted(mcp_dir.glob("*.json")):
        with open(item, "r", encoding="utf-8") as fp:
            data = json.load(fp)
        data["_filename"] = item.name
        data["source"] = "hub"
        result.append(data)
    return result


def save_mcp(hub_path, mcp_data):
    name = validate_mcp_name(mcp_data["name"])
    mcp_dir = get_mcp_dir(hub_path)
    filepath = mcp_dir / f"{name}.json"
    clean = {key: value for key, value in mcp_data.items() if not key.startswith("_")}
    if filepath.exists():
        make_backup(filepath)
    with open(filepath, "w", encoding="utf-8") as fp:
        json.dump(clean, fp, ensure_ascii=False, indent=2)
    with open(filepath, "r", encoding="utf-8") as fp:
        json.load(fp)


def delete_mcp(hub_path, name):
    validate_mcp_name(name)
    mcp_dir = get_mcp_dir(hub_path)
    filepath = mcp_dir / f"{name}.json"
    if filepath.exists():
        filepath.unlink()
        return True
    return False
