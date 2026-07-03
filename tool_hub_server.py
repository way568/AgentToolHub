#!/usr/bin/env python3
"""Tool Hub Server - 跨 Agent 统一管理台（Skill + MCP）"""

import json
import os
import re
import shutil
import subprocess
import ast
import webbrowser
from datetime import datetime, timezone
from fnmatch import fnmatch
from http.server import HTTPServer, BaseHTTPRequestHandler
from pathlib import Path
from urllib.parse import urlparse, parse_qs
from uuid import uuid4

PORT = 8765
CONFIG_FILENAME = "tool-hub.json"
LOG_FILENAME = ".tool-hub-log.jsonl"
DEFAULT_FEEDBACK_URL = "https://cdfc69-sandbox-sessionff6e20bc4f114f3b96-8082.agent.alibaba-inc.com"
# 指针文件：存放在 skill 目录旁，记录用户配置的 hub_path
HUB_PATH_POINTER = Path(__file__).parent / ".hub-path"

# ============================================================
# 配置管理
# ============================================================

def get_default_hub_path():
    """默认推荐路径"""
    return str(Path.home() / "tool-hub")


def get_saved_hub_path():
    """从指针文件读取用户上次设置的 hub_path，没有则返回 None"""
    if HUB_PATH_POINTER.exists():
        return HUB_PATH_POINTER.read_text(encoding="utf-8").strip()
    return None


def save_hub_path_pointer(hub_path):
    """将 hub_path 写入指针文件，下次启动时可找到配置"""
    HUB_PATH_POINTER.write_text(hub_path, encoding="utf-8")


def load_config(hub_path=None):
    """加载配置文件，不存在则返回 None"""
    if not hub_path:
        hub_path = get_saved_hub_path() or get_default_hub_path()
    config_path = Path(hub_path) / CONFIG_FILENAME
    if not config_path.exists():
        return None
    with open(config_path, "r", encoding="utf-8") as f:
        return json.load(f)


def save_config(config):
    """保存配置到文件，同时更新指针文件"""
    hub_path = config.get("hub_path", get_default_hub_path())
    Path(hub_path).mkdir(parents=True, exist_ok=True)
    config_path = Path(hub_path) / CONFIG_FILENAME
    with open(config_path, "w", encoding="utf-8") as f:
        json.dump(config, f, ensure_ascii=False, indent=2)
    save_hub_path_pointer(hub_path)


def normalize_skills_dirs(agent):
    """将 skills_dir 统一为列表格式"""
    sd = agent.get("skills_dir", [])
    if isinstance(sd, str):
        return [sd]
    return sd


# ============================================================
# Agent 预设（声明式）
# ============================================================
#
# 设计原则：
# 1. 不硬编码用户特定路径，全部用 Path.home() / 环境变量 / glob 通配符
# 2. 每个字段提供多个候选路径，按顺序匹配第一个存在的
# 3. skills_dir 候选返回所有命中的目录（可叠加），mcp_config_path 只返回第一个命中
# 4. macOS/Linux/Windows 路径都列出来，跨平台兼容
#
# 添加新 Agent：在 AGENT_PRESETS 加一项即可，无需改其他代码。

def _home():
    return Path.home()


def _glob_first(pattern):
    """返回第一个匹配 glob 模式的存在路径（字符串），无则返回 None"""
    for p in sorted(_home().glob(pattern.lstrip("~/"))):
        if p.exists():
            return str(p)
    return None


def _glob_all(pattern):
    """返回所有匹配 glob 模式的存在路径"""
    return [str(p) for p in sorted(_home().glob(pattern.lstrip("~/"))) if p.exists()]


def _path(*parts):
    """构造 ~/xxx 路径字符串"""
    return str(_home().joinpath(*parts))


AGENT_PRESETS = [
    {
        "id": "claude-code",
        "name": "Claude Code",
        "skills_dir_candidates": [_path(".claude", "skills")],
        # Claude Code 实际挂载的 MCP 以 ~/.claude.json 为准；settings.json 仅作兜底
        "mcp_config_candidates": [
            _path(".claude.json"),
            _path(".claude", "settings.json"),
        ],
        "mcp_config_key": "mcpServers",
    },
    {
        "id": "aone-copilot",
        "name": "Aone Copilot",
        "skills_dir_candidates": [
            _path(".aone_copilot", "skills"),
            _path(".aone_copilot", "plugins", "cache", "git", "obra-superpowers", "5.1.0", "skills"),
            _path(".claude", "skills"),  # 兼容 Claude skill 目录
        ],
        "mcp_config_candidates": [
            _path(".aone_copilot", "mcp_servers.json"),
        ],
        "mcp_config_key": "mcpServers",
    },
    {
        "id": "qoder",
        "name": "Qoder",
        "skills_dir_candidates": [_path(".qoder", "skills")],
        "mcp_config_candidates": [
            # macOS
            _path("Library", "Application Support", "Qoder", "SharedClientCache", "mcp.json"),
            _path("Library", "Application Support", "Qoder", "mcp.json"),
            # Linux
            _path(".config", "Qoder", "mcp.json"),
            # Windows (AppData)
            _path("AppData", "Roaming", "Qoder", "mcp.json"),
        ],
        "mcp_config_key": "mcpServers",
    },
    {
        "id": "qoderwork",
        "name": "QoderWork",
        "skills_dir_candidates": [_path(".qoderwork", "skills")],
        "mcp_config_candidates": [
            _path(".qoderwork", "mcp.json"),
            _path("Library", "Application Support", "QoderWork", "mcp.json"),
            _path(".config", "QoderWork", "mcp.json"),
            _path("AppData", "Roaming", "QoderWork", "mcp.json"),
        ],
        "mcp_config_key": "mcpServers",
    },
    {
        "id": "wukong",
        "name": "悟空",
        # 悟空 UUID 因用户不同而不同，用 glob 匹配
        "skills_dir_glob": ".real/users/user-*/.skills",
        "mcp_config_glob": ".real/users/user-*/.mcp/mcpServerConfig.json",
        "mcp_config_key": "mcpServers",
    },
    {
        "id": "codex",
        "name": "Codex",
        "skills_dir_candidates": [_path(".codex", "skills")],
        "mcp_config_candidates": [_path(".codex", "config.toml")],
        "mcp_config_key": "mcp_servers",
    },
]


def _resolve_preset_paths(preset):
    """根据 preset 解析出实际存在的 skills_dir 和 mcp_config_path"""
    # skills_dir: 收集所有命中的候选（多目录可叠加）
    skills_dirs = []
    for cand in preset.get("skills_dir_candidates", []):
        if Path(cand).is_dir():
            skills_dirs.append(cand)
    glob_pattern = preset.get("skills_dir_glob")
    if glob_pattern:
        skills_dirs.extend(_glob_all(glob_pattern))

    # mcp_config_path: 按优先级取第一个命中的
    mcp_path = None
    for cand in preset.get("mcp_config_candidates", []):
        if Path(cand).is_file():
            mcp_path = cand
            break
    if not mcp_path:
        glob_pattern = preset.get("mcp_config_glob")
        if glob_pattern:
            mcp_path = _glob_first(glob_pattern)

    return skills_dirs, mcp_path


def detect_agents():
    """自动检测已知 Agent，返回包含 skills_dir + mcp_config_path 的完整列表

    只返回至少有一个 skills_dir 命中的 Agent（说明该 Agent 实际安装了）。
    """
    detected = []
    for preset in AGENT_PRESETS:
        skills_dirs, mcp_path = _resolve_preset_paths(preset)
        if not skills_dirs:
            continue  # Agent 未安装
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
    """用 preset 补全已存在 Agent 的缺失字段（不覆盖用户已配置的值）

    只补 mcp_config_path 和 mcp_config_key 这两个新字段，避免破坏用户的 skills_dir 自定义。
    Claude Code 例外：历史版本可能误填 settings.json，需要迁移到实际挂载使用的 ~/.claude.json。
    返回是否有更新。
    """
    preset = next((p for p in AGENT_PRESETS if p["id"] == agent.get("id")), None)
    if not preset:
        return False
    changed = False
    _, mcp_path = _resolve_preset_paths(preset)
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
    """启动时调用：用 preset 补全已配置 Agent 的缺失字段，返回是否有更新"""
    changed = False
    for agent in config.get("agents", []):
        if fill_missing_fields_from_preset(agent):
            changed = True
    return changed


# ============================================================
# 操作日志
# ============================================================

def log_path(hub_path):
    """获取日志文件路径"""
    return Path(hub_path) / LOG_FILENAME


def append_log(hub_path, batch_id, action, skill_name, detail, reversible=True):
    """追加一条操作日志"""
    entry = {
        "id": f"log_{uuid4().hex[:12]}",
        "batch_id": batch_id,
        "ts": datetime.now(timezone.utc).isoformat(),
        "action": action,
        "skill": skill_name,
        "detail": detail,
        "reversible": reversible,
        "rolled_back": False,
    }
    lp = log_path(hub_path)
    lp.parent.mkdir(parents=True, exist_ok=True)
    with open(lp, "a", encoding="utf-8") as f:
        f.write(json.dumps(entry, ensure_ascii=False) + "\n")
    return entry


def read_logs(hub_path, batch_id=None):
    """读取日志，可按 batch_id 筛选"""
    lp = log_path(hub_path)
    if not lp.exists():
        return []
    logs = []
    with open(lp, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            entry = json.loads(line)
            if batch_id and entry.get("batch_id") != batch_id:
                continue
            logs.append(entry)
    return logs


def update_log_entry(hub_path, log_id, updates):
    """更新指定日志条目"""
    lp = log_path(hub_path)
    if not lp.exists():
        return False
    lines = []
    found = False
    with open(lp, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            entry = json.loads(line)
            if entry["id"] == log_id:
                entry.update(updates)
                found = True
            lines.append(json.dumps(entry, ensure_ascii=False))
    if found:
        with open(lp, "w", encoding="utf-8") as f:
            f.write("\n".join(lines) + "\n")
    return found


# ============================================================
# Skill 工具函数
# ============================================================

def parse_skill_md(skill_dir):
    """解析 SKILL.md 的 YAML frontmatter，提取 name 和 description"""
    skill_md = Path(skill_dir) / "SKILL.md"
    if not skill_md.exists():
        return None
    content = skill_md.read_text(encoding="utf-8")
    # 匹配 YAML frontmatter
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
    """推断 skill 来源"""
    skill_path = str(Path(skill_path).resolve())
    hub_resolved = str(Path(hub_path).resolve())
    # 在中央仓库下 → 自研
    if skill_path.startswith(hub_resolved):
        return "自研"
    # 在某 agent 目录下且不是 ln → agent内置
    for agent in agents:
        for d in normalize_skills_dirs(agent):
            agent_dir = str(Path(d).resolve())
            if skill_path.startswith(agent_dir) and not Path(skill_path).is_symlink():
                return f"{agent['name']}-内置"
    # 有 .git 目录
    git_dir = Path(skill_path) / ".git"
    if git_dir.exists():
        # 检查 remote
        git_config = git_dir / "config" if git_dir.is_dir() else None
        if git_config and git_config.exists():
            gc_content = git_config.read_text(encoding="utf-8", errors="ignore")
            remote_match = re.search(r'url\s*=\s*(.+)', gc_content)
            if remote_match:
                return remote_match.group(1).strip()
    return "未知"


def is_excluded(name, excludes):
    """检查 skill 名称是否在排除列表中（支持 fnmatch 通配符）"""
    for pattern in excludes:
        if fnmatch(name, pattern):
            return True
    return False


# ============================================================
# MCP 管理
# ============================================================

MCP_DIR_NAME = "mcp"
MCP_ADAPTERS_DIR = Path(__file__).parent / "mcp-adapters"

def get_mcp_dir(hub_path):
    """获取 MCP 归聚存档目录"""
    mcp_dir = Path(hub_path) / MCP_DIR_NAME
    mcp_dir.mkdir(parents=True, exist_ok=True)
    return mcp_dir

def load_all_mcp(hub_path):
    """加载所有 MCP 归聚存档"""
    mcp_dir = get_mcp_dir(hub_path)
    result = []
    for f in sorted(mcp_dir.glob("*.json")):
        with open(f, "r", encoding="utf-8") as fp:
            data = json.load(fp)
            data["_filename"] = f.name
            data["source"] = "hub"
            result.append(data)
    return result


def parse_agent_mcp_to_standard(name, raw_config):
    """把某个 Agent 配置里的一条 MCP 反向解析成标准格式"""
    if not isinstance(raw_config, dict):
        return None
    std = {"name": name, "description": raw_config.get("description", "")}
    if "command" in raw_config:
        std["type"] = "stdio"
        std["command"] = raw_config.get("command", "")
        std["args"] = raw_config.get("args", []) or []
        if raw_config.get("env"):
            std["env"] = raw_config["env"]
    elif raw_config.get("type") == "sse" or "/sse" in raw_config.get("url", ""):
        std["type"] = "sse"
        std["url"] = raw_config.get("url", "")
    elif raw_config.get("type") in ("http", "streamableHttp"):
        std["type"] = "streamableHttp"
        std["url"] = raw_config.get("url", "")
    elif "url" in raw_config:
        std["type"] = raw_config.get("type", "sse")
        std["url"] = raw_config["url"]
    else:
        std["type"] = "unknown"
    if raw_config.get("headers"):
        std["headers"] = raw_config["headers"]
    elif raw_config.get("http_headers"):
        std["headers"] = raw_config["http_headers"]
    return std


def scan_unmanaged_mcp(agents, managed_names):
    """扫描各 Agent 配置文件中尚未归聚到 Hub 的 MCP

    返回结构: [{name, type, ..., source: "agent", source_agents: [agent_id, ...]}]
    同名 MCP 在多个 Agent 中只生成一条，source_agents 记录所有来源。
    """
    unmanaged_map = {}
    for agent in agents:
        agent_mcps = read_agent_mcp_config(agent)
        for name, raw_cfg in agent_mcps.items():
            if name in managed_names:
                continue
            std = parse_agent_mcp_to_standard(name, raw_cfg)
            if not std:
                continue
            if name in unmanaged_map:
                unmanaged_map[name]["source_agents"].append(agent["id"])
            else:
                std["source"] = "agent"
                std["source_agents"] = [agent["id"]]
                unmanaged_map[name] = std
    return list(unmanaged_map.values())

def save_mcp(hub_path, mcp_data):
    """保存单个 MCP 到归聚存档"""
    mcp_dir = get_mcp_dir(hub_path)
    name = mcp_data["name"]
    filepath = mcp_dir / f"{name}.json"
    # 写入时排除内部字段
    clean = {k: v for k, v in mcp_data.items() if not k.startswith("_")}
    with open(filepath, "w", encoding="utf-8") as fp:
        json.dump(clean, fp, ensure_ascii=False, indent=2)

def delete_mcp(hub_path, name):
    """从归聚存档删除 MCP"""
    mcp_dir = get_mcp_dir(hub_path)
    filepath = mcp_dir / f"{name}.json"
    if filepath.exists():
        filepath.unlink()
        return True
    return False

def load_adapter(agent_id):
    """加载 Agent 的 MCP 适配器规则"""
    adapter_file = MCP_ADAPTERS_DIR / f"{agent_id}.json"
    if adapter_file.exists():
        with open(adapter_file, "r", encoding="utf-8") as fp:
            return json.load(fp)
    return None

def _get_mcp_config_paths(agent):
    """获取 Agent 的 MCP 配置文件路径列表（兼容单值和数组）"""
    raw = agent.get("mcp_config_path", "")
    if not raw:
        return []
    if isinstance(raw, list):
        return [Path(p).expanduser() for p in raw if p]
    return [Path(raw).expanduser()]


def _parse_toml_value(raw):
    raw = raw.strip()
    if not raw:
        return ""
    try:
        return ast.literal_eval(raw)
    except (ValueError, SyntaxError):
        lowered = raw.lower()
        if lowered == "true":
            return True
        if lowered == "false":
            return False
        if re.fullmatch(r"-?\d+", raw):
            return int(raw)
        return raw.strip('"').strip("'")


def _toml_quote(value):
    return json.dumps(str(value), ensure_ascii=False)


def _toml_value(value):
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (int, float)):
        return str(value)
    if isinstance(value, list):
        return "[" + ", ".join(_toml_value(v) for v in value) + "]"
    return _toml_quote(value)


def _read_toml_mcp_config(config_path, config_key):
    """读取 Codex 风格 TOML MCP 配置: [mcp_servers.name] / [mcp_servers.name.env]"""
    merged = {}
    current_name = None
    current_child = None
    section_re = re.compile(r"^\s*\[([^\]]+)\]\s*$")
    kv_re = re.compile(r"^\s*([A-Za-z0-9_-]+)\s*=\s*(.+?)\s*(?:#.*)?$")
    with open(config_path, "r", encoding="utf-8") as fp:
        for line in fp:
            section_match = section_re.match(line)
            if section_match:
                parts = section_match.group(1).split(".")
                current_name = None
                current_child = None
                if len(parts) >= 2 and parts[0] == config_key:
                    current_name = parts[1].strip('"')
                    merged.setdefault(current_name, {})
                    if len(parts) >= 3:
                        current_child = parts[2].strip('"')
                        merged[current_name].setdefault(current_child, {})
                continue
            if not current_name:
                continue
            kv_match = kv_re.match(line)
            if not kv_match:
                continue
            key, raw_value = kv_match.groups()
            target = merged[current_name]
            if current_child:
                target = target.setdefault(current_child, {})
            target[key] = _parse_toml_value(raw_value)
    return merged


def _toml_mcp_sections(config_key, mcp_name, mcp_config):
    lines = [f"[{config_key}.{mcp_name}]"]
    child_tables = {}
    for key, value in mcp_config.items():
        if isinstance(value, dict):
            child_tables[key] = value
        else:
            lines.append(f"{key} = {_toml_value(value)}")
    for child_key, child_value in child_tables.items():
        lines.append("")
        lines.append(f"[{config_key}.{mcp_name}.{child_key}]")
        for key, value in child_value.items():
            lines.append(f"{key} = {_toml_value(value)}")
    return "\n".join(lines) + "\n"


def _remove_toml_mcp_sections(content, config_key, mcp_name):
    section_re = re.compile(r"^\s*\[([^\]]+)\]\s*$")
    kept = []
    skipping = False
    removed = False
    for line in content.splitlines(keepends=True):
        section_match = section_re.match(line)
        if section_match:
            section = section_match.group(1)
            prefix = f"{config_key}.{mcp_name}"
            skipping = section == prefix or section.startswith(prefix + ".")
            if skipping:
                removed = True
                continue
        if not skipping:
            kept.append(line)
    return "".join(kept).rstrip() + "\n", removed


def _write_toml_mcp_entry(config_path, config_key, mcp_name, mcp_config):
    content = config_path.read_text(encoding="utf-8")
    content, _ = _remove_toml_mcp_sections(content, config_key, mcp_name)
    content = content.rstrip() + "\n\n" + _toml_mcp_sections(config_key, mcp_name, mcp_config)
    config_path.write_text(content, encoding="utf-8")
    return True


def _remove_toml_mcp_entry(config_path, config_key, mcp_name):
    content = config_path.read_text(encoding="utf-8")
    content, removed = _remove_toml_mcp_sections(content, config_key, mcp_name)
    if removed:
        config_path.write_text(content, encoding="utf-8")
    return removed


def read_agent_mcp_config(agent):
    """读取某个 Agent 当前的 MCP 配置（支持多文件合并）"""
    config_key = agent.get("mcp_config_key", "mcpServers")
    merged = {}
    for config_path in _get_mcp_config_paths(agent):
        if not config_path.is_file():
            continue
        try:
            if config_path.suffix == ".toml":
                servers = _read_toml_mcp_config(config_path, config_key)
            else:
                with open(config_path, "r", encoding="utf-8") as fp:
                    data = json.load(fp)
                servers = data.get(config_key, {})
            if isinstance(servers, dict):
                merged.update(servers)
        except (json.JSONDecodeError, IOError, OSError):
            continue
    return merged

def write_agent_mcp_entry(agent, mcp_name, mcp_config):
    """向 Agent 配置文件写入一条 MCP（写入第一个存在的配置文件）"""
    config_key = agent.get("mcp_config_key", "mcpServers")
    for config_path in _get_mcp_config_paths(agent):
        if not config_path.is_file():
            continue
        if config_path.suffix == ".toml":
            return _write_toml_mcp_entry(config_path, config_key, mcp_name, mcp_config)
        with open(config_path, "r", encoding="utf-8") as fp:
            data = json.load(fp)
        if config_key not in data:
            data[config_key] = {}
        data[config_key][mcp_name] = mcp_config
        with open(config_path, "w", encoding="utf-8") as fp:
            json.dump(data, fp, ensure_ascii=False, indent=2)
        return True
    return False

def remove_agent_mcp_entry(agent, mcp_name):
    """从 Agent 配置文件移除一条 MCP（遍历所有配置文件，找到并删除）"""
    config_key = agent.get("mcp_config_key", "mcpServers")
    removed = False
    for config_path in _get_mcp_config_paths(agent):
        if not config_path.is_file():
            continue
        if config_path.suffix == ".toml":
            removed = _remove_toml_mcp_entry(config_path, config_key, mcp_name) or removed
            continue
        with open(config_path, "r", encoding="utf-8") as fp:
            data = json.load(fp)
        servers = data.get(config_key, {})
        if mcp_name in servers:
            del servers[mcp_name]
            with open(config_path, "w", encoding="utf-8") as fp:
                json.dump(data, fp, ensure_ascii=False, indent=2)
            removed = True
    return removed

def adapt_mcp_for_agent(mcp_data, agent_id):
    """将标准格式 MCP 转换为目标 Agent 的格式"""
    adapter = load_adapter(agent_id)
    mcp_type = mcp_data.get("type", "stdio")
    if adapter is None:
        return _build_raw_config(mcp_data)
    mapping = adapter.get("type_mapping", {}).get(mcp_type)
    if mapping is None:
        return _build_raw_config(mcp_data)
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

def _build_raw_config(mcp_data):
    """无适配器时的原样透传"""
    mcp_type = mcp_data.get("type", "stdio")
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

def fetch_mcp_tools_description(mcp_data):
    """连接 MCP 获取 tools/list，返回自动生成的描述字符串；失败返回 None"""
    import subprocess
    mcp_type = mcp_data.get("type", "stdio")

    try:
        if mcp_type == "stdio":
            cmd = mcp_data.get("command", "")
            args = mcp_data.get("args", []) or []
            env_override = mcp_data.get("env", {})
            full_cmd = [cmd] + args
            env = dict(os.environ)
            env.update(env_override)
            # 启动子进程，通过 stdin/stdout 交互 JSON-RPC
            proc = subprocess.Popen(full_cmd, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, env=env)
            # 发送 initialize
            init_req = json.dumps({"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {"protocolVersion": "2025-03-26", "capabilities": {}, "clientInfo": {"name": "tool-hub", "version": "1.0"}}}) + "\n"
            proc.stdin.write(init_req.encode())
            proc.stdin.flush()
            # 读取 initialize 响应
            init_resp_line = proc.stdout.readline()
            if not init_resp_line:
                proc.kill()
                return None
            # 发送 initialized 通知
            notif = json.dumps({"jsonrpc": "2.0", "method": "notifications/initialized"}) + "\n"
            proc.stdin.write(notif.encode())
            proc.stdin.flush()
            # 发送 tools/list
            tools_req = json.dumps({"jsonrpc": "2.0", "id": 2, "method": "tools/list", "params": {}}) + "\n"
            proc.stdin.write(tools_req.encode())
            proc.stdin.flush()
            # 读取 tools/list 响应
            tools_resp_line = proc.stdout.readline()
            proc.kill()
            if not tools_resp_line:
                return None
            tools_resp = json.loads(tools_resp_line)
            tools = tools_resp.get("result", {}).get("tools", [])
        else:
            # HTTP 类型（streamableHttp / sse）
            import urllib.request
            url = mcp_data.get("url", "")
            if not url:
                return None
            headers = {"Content-Type": "application/json", "Accept": "application/json, text/event-stream"}
            for k, v in mcp_data.get("headers", {}).items():
                headers[k] = v

            # 支持 POST 重定向（Cloudflare Tunnel 307）
            class _RedirectHandler(urllib.request.HTTPRedirectHandler):
                def redirect_request(self, req, fp, code, msg, hdrs, newurl):
                    return urllib.request.Request(
                        newurl, data=req.data, method=req.get_method(),
                        headers=dict(req.header_items()))
            opener = urllib.request.build_opener(_RedirectHandler)

            # initialize
            init_payload = json.dumps({"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {"protocolVersion": "2025-03-26", "capabilities": {}, "clientInfo": {"name": "tool-hub", "version": "1.0"}}}).encode()
            req = urllib.request.Request(url, data=init_payload, method="POST", headers=headers)
            with opener.open(req, timeout=10) as resp:
                resp.read()  # consume
            # tools/list
            tools_payload = json.dumps({"jsonrpc": "2.0", "id": 2, "method": "tools/list", "params": {}}).encode()
            req2 = urllib.request.Request(url, data=tools_payload, method="POST", headers=headers)
            with opener.open(req2, timeout=10) as resp2:
                body = resp2.read().decode()
            # 解析（可能是 JSON 或 SSE 格式）
            tools = []
            stripped = body.strip()
            if stripped.startswith("{"):
                tools_resp = json.loads(stripped)
                tools = tools_resp.get("result", {}).get("tools", [])
            else:
                # SSE 格式：提取所有 data: 行拼接后解析
                data_parts = []
                for line in body.split("\n"):
                    if line.startswith("data:"):
                        data_parts.append(line[5:].strip())
                if data_parts:
                    combined = "".join(data_parts)
                    try:
                        parsed = json.loads(combined)
                        tools = parsed.get("result", {}).get("tools", [])
                    except json.JSONDecodeError:
                        pass

        if not tools:
            return None
        # 生成描述：列出前 5 个工具名
        tool_names = [t.get("name", "") for t in tools if t.get("name")]
        total = len(tool_names)
        preview = ", ".join(tool_names[:5])
        if total > 5:
            return f"提供 {total} 个工具：{preview} 等"
        elif total > 0:
            return f"提供 {total} 个工具：{preview}"
        return None
    except Exception:
        return None


def test_mcp_connectivity(mcp_data):
    """测试 MCP 连通性"""
    mcp_type = mcp_data.get("type", "stdio")
    if mcp_type == "stdio":
        cmd = mcp_data.get("command", "")
        found = shutil.which(cmd) is not None
        return {"status": "ok" if found else "error",
                "detail": f"command '{cmd}' {'found' if found else 'not found'}"}
    url = mcp_data.get("url", "")
    if not url:
        return {"status": "error", "detail": "no url"}
    try:
        import urllib.request
        import urllib.error

        # 自定义 opener 支持 POST 重定向（Cloudflare Tunnel 等会返回 307）
        class RedirectHandler(urllib.request.HTTPRedirectHandler):
            def redirect_request(self, req, fp, code, msg, headers, newurl):
                new_req = urllib.request.Request(
                    newurl, data=req.data, method=req.get_method(),
                    headers=dict(req.header_items()))
                return new_req

        opener = urllib.request.build_opener(RedirectHandler)

        if mcp_type == "streamableHttp":
            # Streamable HTTP MCP 使用 POST + JSON-RPC initialize
            payload = json.dumps({"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {"protocolVersion": "2025-03-26", "capabilities": {}, "clientInfo": {"name": "tool-hub-test", "version": "1.0"}}}).encode("utf-8")
            req = urllib.request.Request(url, data=payload, method="POST")
            req.add_header("Content-Type", "application/json")
            req.add_header("Accept", "application/json, text/event-stream")
        else:
            # SSE 类型用 GET
            req = urllib.request.Request(url, method="GET")
            req.add_header("Accept", "text/event-stream")
        # 透传自定义 headers（如 API key）
        for header_name, header_value in mcp_data.get("headers", {}).items():
            req.add_header(header_name, header_value)
        with opener.open(req, timeout=10) as resp:
            return {"status": "ok", "detail": f"HTTP {resp.status}"}
    except Exception as e:
        error_str = str(e)
        # 某些 MCP 服务端返回非 2xx 但实际可达（如 401 需要认证），区分处理
        if "HTTP Error" in error_str:
            code = error_str.split("HTTP Error ")[1].split(":")[0] if "HTTP Error " in error_str else ""
            if code in ("401", "403"):
                return {"status": "ok", "detail": f"可达但需认证 (HTTP {code})"}
        return {"status": "error", "detail": error_str}


# ============================================================
# HTTP 请求处理器
# ============================================================

# ============================================================
# 代理检测
# ============================================================

PROXY_HEADER_NAMES = [
    "Via",
    "X-Forwarded-For",
    "X-Forwarded-Host",
    "X-Forwarded-Proto",
    "Forwarded",
    "X-Real-IP",
    "Proxy-Connection",
]

def detect_proxy_from_headers(headers):
    """从请求头中检测代理信息

    返回 dict，包含 detected (bool)、headers (dict)、summary (str)。
    """
    detected_headers = {}
    for name in PROXY_HEADER_NAMES:
        value = headers.get(name)
        if value:
            detected_headers[name] = value

    detected = len(detected_headers) > 0
    summary = ""
    if detected:
        parts = [f"{k}={v}" for k, v in detected_headers.items()]
        summary = f"检测到代理标记: {', '.join(parts)}"

    return {
        "detected": detected,
        "headers": detected_headers,
        "summary": summary,
    }


class SkillHubHandler(BaseHTTPRequestHandler):
    """Tool Hub HTTP 请求处理器"""

    def log_message(self, format, *args):
        """自定义日志格式"""
        print(f"[{datetime.now().strftime('%H:%M:%S')}] {args[0]}")

    def _detect_proxy(self):
        """检测当前请求是否经由代理转发，返回代理信息 dict"""
        return detect_proxy_from_headers(self.headers)

    def send_json(self, data, status=200):
        """发送 JSON 响应"""
        body = json.dumps(data, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Access-Control-Allow-Origin", "*")
        # 代理告警头
        proxy_info = self._detect_proxy()
        if proxy_info["detected"]:
            self.send_header("X-Tool-Hub-Proxy-Warning", "proxy-detected")
            self.send_header("X-Tool-Hub-Proxy-Headers", ", ".join(proxy_info["headers"].keys()))
        self.end_headers()
        self.wfile.write(body)

    def send_error_json(self, message, status=400):
        """发送错误 JSON 响应"""
        self.send_json({"error": message}, status)

    def read_body(self):
        """读取请求体并解析为 JSON"""
        length = int(self.headers.get("Content-Length", 0))
        if length == 0:
            return {}
        raw = self.rfile.read(length)
        return json.loads(raw.decode("utf-8"))

    def get_config_or_uninit(self):
        """获取配置，未初始化返回 None"""
        config = load_config()  # 自动查找指针文件或默认路径
        return config

    # ------ 路由分发 ------

    def do_OPTIONS(self):
        """处理 CORS 预检请求"""
        self.send_response(204)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, PUT, DELETE, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.end_headers()

    def do_GET(self):
        parsed = urlparse(self.path)
        path = parsed.path.rstrip("/")
        query = parse_qs(parsed.query)

        if path == "" or path == "/":
            self.serve_index()
        elif path == "/api/config":
            self.handle_get_config()
        elif path == "/api/agents":
            self.handle_get_agents()
        elif path == "/api/agent-onboarding-prompt":
            self.handle_get_agent_onboarding_prompt()
        elif path == "/api/skills":
            self.handle_get_skills()
        elif path == "/api/logs":
            batch_id = query.get("batch_id", [None])[0]
            self.handle_get_logs(batch_id)
        elif path == "/api/user-info":
            self.handle_get_user_info()
        elif path == "/api/network-info":
            self.handle_get_network_info()
        elif path == "/api/mcp":
            self.handle_get_mcp()
        else:
            self.send_error_json("Not Found", 404)

    def do_POST(self):
        parsed = urlparse(self.path)
        path = parsed.path.rstrip("/")

        if path == "/api/choose-folder":
            self.handle_choose_folder()
        elif path == "/api/choose-file":
            self.handle_choose_file()
        elif path == "/api/agents/upsert":
            self.handle_upsert_agent()
        elif path == "/api/agents":
            self.handle_add_agent()
        elif path == "/api/scan":
            self.handle_scan()
        elif path == "/api/gather":
            self.handle_gather()
        elif path == "/api/sync":
            self.handle_sync()
        elif path == "/api/scan-sync":
            self.handle_scan_sync()
        elif re.match(r"^/api/skills/[^/]+/toggle$", path):
            skill_id = path.split("/")[3]
            self.handle_toggle_skill(skill_id)
        elif re.match(r"^/api/logs/[^/]+/rollback$", path):
            batch_id = path.split("/")[3]
            self.handle_rollback_batch(batch_id)
        elif re.match(r"^/api/logs/[^/]+/undo$", path):
            log_id = path.split("/")[3]
            self.handle_undo_single(log_id)
        elif path == "/api/mcp":
            self.handle_add_mcp()
        elif path == "/api/mcp/gather":
            self.handle_gather_mcp()
        elif re.match(r"^/api/mcp/[^/]+/test$", path):
            mcp_name = path.split("/")[3]
            self.handle_test_mcp(mcp_name)
        elif re.match(r"^/api/mcp/[^/]+/toggle$", path):
            mcp_name = path.split("/")[3]
            self.handle_toggle_mcp(mcp_name)
        elif path == "/api/skills/upload":
            self.handle_upload_skill()
        else:
            self.send_error_json("Not Found", 404)

    def do_PUT(self):
        parsed = urlparse(self.path)
        path = parsed.path.rstrip("/")

        if path == "/api/config":
            self.handle_put_config()
        elif re.match(r"^/api/agents/[^/]+$", path):
            agent_id = path.split("/")[3]
            self.handle_edit_agent(agent_id)
        elif re.match(r"^/api/mcp/[^/]+$", path):
            mcp_name = path.split("/")[3]
            self.handle_edit_mcp(mcp_name)
        else:
            self.send_error_json("Not Found", 404)

    def do_DELETE(self):
        parsed = urlparse(self.path)
        path = parsed.path.rstrip("/")

        if re.match(r"^/api/agents/[^/]+$", path):
            agent_id = path.split("/")[3]
            self.handle_delete_agent(agent_id)
        elif re.match(r"^/api/mcp/[^/]+$", path):
            mcp_name = path.split("/")[3]
            self.handle_delete_mcp(mcp_name)
        elif re.match(r"^/api/skills/[^/]+$", path):
            skill_id = path.split("/")[3]
            self.handle_delete_skill(skill_id)
        else:
            self.send_error_json("Not Found", 404)

    # ------ 具体处理函数 ------

    def serve_index(self):
        """返回 index.html"""
        index_path = Path(__file__).parent / "index.html"
        if not index_path.exists():
            self.send_error_json("index.html not found", 404)
            return
        content = index_path.read_bytes()
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(content)))
        self.end_headers()
        self.wfile.write(content)

    def handle_get_user_info(self):
        """GET /api/user-info — 返回本机用户标识"""
        import socket
        username = Path.home().name
        hostname = socket.gethostname().replace(".local", "")
        self.send_json({"user": f"{username}@{hostname}"})

    def handle_get_network_info(self):
        """GET /api/network-info — 返回网络状态、代理检测结果"""
        import socket

        # 1. 代理检测
        proxy_info = self._detect_proxy()

        # 2. 客户端地址
        client_host, client_port = self.client_address

        # 3. 服务端绑定信息
        server_host = self.server.server_address[0]
        server_port = self.server.server_address[1]

        # 4. 本机 IP 列表
        hostname = socket.gethostname()
        local_ips = []
        try:
            addrs = socket.getaddrinfo(hostname, None, socket.AF_INET)
            local_ips = sorted(set(a[4][0] for a in addrs))
        except Exception:
            local_ips = ["127.0.0.1"]

        # 5. 服务端口状态（检查是否仍在监听）
        import socket as sock_mod
        port_listening = False
        port_error = None
        try:
            s = sock_mod.socket(sock_mod.AF_INET, sock_mod.SOCK_STREAM)
            s.settimeout(1)
            result = s.connect_ex(("127.0.0.1", server_port))
            s.close()
            port_listening = (result == 0)
        except Exception as e:
            port_error = str(e)

        result = {
            "server": {
                "host": server_host,
                "port": server_port,
                "listening": port_listening,
            },
            "client": f"{client_host}:{client_port}",
            "proxy": {
                "detected": proxy_info["detected"],
                "summary": proxy_info["summary"],
                "headers": proxy_info["headers"],
            },
            "local_ips": local_ips,
        }
        if port_error:
            result["port_error"] = port_error

        self.send_json(result)

    def handle_get_config(self):
        """GET /api/config"""
        config = self.get_config_or_uninit()
        if config is None:
            self.send_json({"initialized": False})
        else:
            config["initialized"] = True
            if "feedback_url" not in config:
                config["feedback_url"] = DEFAULT_FEEDBACK_URL
            self.send_json(config)

    def handle_put_config(self):
        """PUT /api/config - 更新/初始化配置"""
        body = self.read_body()
        hub_path = body.get("hub_path", get_default_hub_path())
        global_exclude = body.get("global_exclude", [])

        # 加载已有配置或创建新配置
        existing = load_config(hub_path)
        if existing:
            existing["hub_path"] = hub_path
            existing["global_exclude"] = global_exclude
            config = existing
        else:
            # 首次初始化
            agents = detect_agents()
            config = {
                "hub_path": hub_path,
                "global_exclude": global_exclude,
                "agents": agents,
                "skills": {},
            }

        save_config(config)
        batch_id = f"config_{uuid4().hex[:8]}"
        append_log(hub_path, batch_id, "config", "", {"action": "update_config", "hub_path": hub_path}, reversible=False)
        config["initialized"] = True
        self.send_json(config)

    def handle_get_agents(self):
        """GET /api/agents"""
        config = self.get_config_or_uninit()
        if not config:
            self.send_json([])
            return
        self.send_json(config.get("agents", []))

    def handle_get_agent_onboarding_prompt(self):
        """GET /api/agent-onboarding-prompt - 生成未知 Agent 自助接入 Prompt"""
        config = self.get_config_or_uninit()
        if not config:
            self.send_error_json("系统未初始化")
            return

        hub_path = config.get("hub_path", get_default_hub_path())
        config_path = str(Path(hub_path) / CONFIG_FILENAME)
        agents = [
            {"id": agent.get("id"), "name": agent.get("name")}
            for agent in config.get("agents", [])
        ]
        schema = {
            "id": "当前 agent 的稳定英文 id",
            "name": "当前 Agent 的显示名称",
            "skills_dir": ["检测到的 Skills 目录绝对路径"],
            "mcp_config_path": "检测到的 MCP 配置文件绝对路径；没有则省略或留空",
            "mcp_config_key": "检测到的 MCP 配置 key；没有则使用 mcpServers",
        }
        prompt = f"""你现在需要把当前这个 Agent 接入 Tool Hub。

请你自动检测当前 Agent 的本地配置，并将结果写入 Tool Hub。

Tool Hub 信息：
- 服务地址：http://localhost:{PORT}
- 配置文件：{config_path}
- 已有 Agent：{json.dumps(agents, ensure_ascii=False)}

请完成以下任务：

1. 判断当前 Agent 的显示名称和稳定英文 id。
   - id 使用小写英文、数字和短横线，例如 cursor、qoder、my-agent。
   - name 使用用户可读名称，例如 Cursor、Qoder、XXX Agent。

2. 自动检测当前 Agent 的 Skills 目录。
   优先查找这些可能路径：
   - 当前 Agent 官方配置目录下的 skills 目录
   - ~/.当前agent名/skills
   - ~/.当前agent名/.skills
   - 当前工作区或配置目录中包含 SKILL.md 的父目录

3. 自动检测当前 Agent 的 MCP 配置文件。
   优先查找这些可能文件：
   - mcp.json
   - mcp_servers.json
   - settings.json
   - config.json
   - 当前 Agent 官方 MCP 配置文件

4. 识别 MCP 配置所在 JSON key。
   优先识别：
   - mcpServers
   - servers
   - tools

5. 如果找不到 MCP 配置，可以只接入 Skills。
   如果找不到 Skills，可以只接入 MCP。
   但至少需要找到其中一个，否则不要写入，并说明原因。

6. 优先通过 Tool Hub API 写入：
   POST http://localhost:{PORT}/api/agents/upsert

   请求体必须使用以下结构：
{json.dumps(schema, ensure_ascii=False, indent=2)}

7. 如果 Tool Hub API 不可用，则直接修改配置文件：
   {config_path}

   修改要求：
   - 写入前先备份为 tool-hub.json.bak-时间戳
   - 只新增或更新 agents 数组中的当前 Agent
   - 不覆盖其他 Agent 配置
   - 写入后校验 JSON 格式有效

8. 最后输出接入报告：
   - Agent id
   - Agent name
   - Skills 目录
   - MCP 配置文件
   - MCP 配置 key
   - 写入方式：API 或直接文件
   - 是否成功
   - 如果失败，给出原因和下一步建议
"""
        self.send_json({"prompt": prompt})

    def handle_choose_file(self):
        """POST /api/choose-file - 调用 macOS 原生文件选择器"""
        body = self.read_body()
        default_path = body.get("default_path", "").strip()
        if default_path:
            default_path = str(Path(default_path).expanduser())
        try:
            if default_path and Path(default_path).parent.is_dir():
                folder = str(Path(default_path).parent)
                script = f'POSIX path of (choose file with prompt "选择文件" default location (POSIX file "{folder}"))'
            else:
                script = 'POSIX path of (choose file with prompt "选择文件" default location (POSIX file (POSIX path of (path to home folder))))'
            result = subprocess.run(
                ["osascript", "-e", script],
                capture_output=True, text=True, timeout=120
            )
            if result.returncode != 0:
                self.send_json({"path": "", "cancelled": True})
                return
            file_path = result.stdout.strip()
            self.send_json({"path": file_path, "cancelled": False})
        except subprocess.TimeoutExpired:
            self.send_json({"path": "", "cancelled": True})
        except Exception as e:
            self.send_error_json(f"选择文件失败: {e}")

    def handle_choose_folder(self):
        """POST /api/choose-folder - 调用 macOS 原生目录选择器"""
        body = self.read_body()
        default_path = body.get("default_path", "").strip()
        # 展开 ~ 为用户主目录
        if default_path:
            default_path = str(Path(default_path).expanduser())
        try:
            # 如果指定了默认路径且存在，就定位到该目录；否则定位到 home
            if default_path and Path(default_path).is_dir():
                script = f'POSIX path of (choose folder with prompt "选择目录" default location (POSIX file "{default_path}"))'
            else:
                script = 'POSIX path of (choose folder with prompt "选择目录" default location (POSIX file (POSIX path of (path to home folder))))'
            result = subprocess.run(
                ["osascript", "-e", script],
                capture_output=True, text=True, timeout=120
            )
            if result.returncode != 0:
                self.send_json({"path": "", "cancelled": True})
                return
            folder_path = result.stdout.strip().rstrip("/")
            self.send_json({"path": folder_path, "cancelled": False})
        except subprocess.TimeoutExpired:
            self.send_json({"path": "", "cancelled": True})
        except Exception as e:
            self.send_error_json(f"选择目录失败: {e}")

    def build_agent_from_body(self, body, fallback_id=None):
        """从请求体构造标准 Agent 配置"""
        name = body.get("name", "").strip()
        skills_dir = body.get("skills_dir", [])
        mcp_config_path = body.get("mcp_config_path", "").strip()
        if isinstance(skills_dir, str):
            skills_dir_list = [skills_dir] if skills_dir.strip() else []
        else:
            skills_dir_list = [str(path).strip() for path in skills_dir if str(path).strip()]
        if not name:
            raise ValueError("缺少必填字段: name")
        if not skills_dir_list and not mcp_config_path:
            raise ValueError("至少需要提供 skills_dir 或 mcp_config_path")
        agent_id = body.get("id") or fallback_id or re.sub(r'[^a-z0-9]+', '-', name.lower()).strip('-')
        agent_id = re.sub(r'[^a-z0-9-]+', '-', agent_id.lower()).strip('-')
        if not agent_id:
            raise ValueError("无法生成有效 Agent ID")
        agent = {"id": agent_id, "name": name, "skills_dir": skills_dir_list}
        if mcp_config_path:
            agent["mcp_config_path"] = mcp_config_path
        agent["mcp_config_key"] = body.get("mcp_config_key", "mcpServers") or "mcpServers"
        return agent

    def handle_add_agent(self):
        """POST /api/agents"""
        config = self.get_config_or_uninit()
        if not config:
            self.send_error_json("系统未初始化，请先 PUT /api/config")
            return
        body = self.read_body()
        try:
            new_agent = self.build_agent_from_body(body)
        except ValueError as error:
            self.send_error_json(str(error))
            return
        for agent in config.get("agents", []):
            if agent["id"] == new_agent["id"]:
                self.send_error_json(f"Agent ID '{new_agent['id']}' 已存在")
                return
        config.setdefault("agents", []).append(new_agent)
        save_config(config)
        self.send_json({"ok": True, "agent": new_agent})

    def handle_upsert_agent(self):
        """POST /api/agents/upsert - 新增或更新 Agent，供未知 Agent 自助接入"""
        config = self.get_config_or_uninit()
        if not config:
            self.send_error_json("系统未初始化，请先 PUT /api/config")
            return
        body = self.read_body()
        try:
            incoming_agent = self.build_agent_from_body(body)
        except ValueError as error:
            self.send_error_json(str(error))
            return
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
            self.send_error_json("Agent ID 和名称分别命中了不同的现有 Agent，请手动处理冲突")
            return

        target_index = existing_by_id_index
        if target_index is None:
            target_index = existing_by_name_index
        if target_index is not None:
            agents[target_index] = incoming_agent
            save_config(config)
            self.send_json({"ok": True, "action": "updated", "agent": incoming_agent})
            return

        agents.append(incoming_agent)
        save_config(config)
        self.send_json({"ok": True, "action": "created", "agent": incoming_agent})

    def handle_edit_agent(self, agent_id):
        """PUT /api/agents/<id>"""
        config = self.get_config_or_uninit()
        if not config:
            self.send_error_json("系统未初始化")
            return
        body = self.read_body()
        for agent in config.get("agents", []):
            if agent["id"] == agent_id:
                if "name" in body:
                    agent["name"] = body["name"]
                if "skills_dir" in body:
                    sd = body["skills_dir"]
                    agent["skills_dir"] = [sd] if isinstance(sd, str) else sd
                if "mcp_config_path" in body:
                    agent["mcp_config_path"] = body["mcp_config_path"]
                if "mcp_config_key" in body:
                    agent["mcp_config_key"] = body["mcp_config_key"]
                save_config(config)
                self.send_json({"ok": True, "agent": agent})
                return
        self.send_error_json(f"Agent '{agent_id}' 不存在", 404)

    def handle_delete_agent(self, agent_id):
        """DELETE /api/agents/<id>"""
        config = self.get_config_or_uninit()
        if not config:
            self.send_error_json("系统未初始化")
            return
        agents = config.get("agents", [])
        new_agents = [a for a in agents if a["id"] != agent_id]
        if len(new_agents) == len(agents):
            self.send_error_json(f"Agent '{agent_id}' 不存在", 404)
            return
        config["agents"] = new_agents
        save_config(config)
        self.send_json({"ok": True})

    def handle_get_skills(self):
        """GET /api/skills - 获取所有 skill（已管理 + 各 agent 目录下已有的）"""
        config = self.get_config_or_uninit()
        if not config:
            self.send_json([])
            return
        hub_path = config["hub_path"]
        managed_skills = config.get("skills", {})
        agents = config.get("agents", [])
        global_exclude = config.get("global_exclude", [])
        seen = {}  # skill_id -> skill_info

        # 1. 已管理的 skill（config.skills 中记录的）
        for skill_id, skill_info in managed_skills.items():
            skill_path = skill_info.get("path", "")
            source = skill_info.get("source", infer_source(skill_path, hub_path, agents))
            mtime = 0
            skill_md = Path(skill_path) / "SKILL.md" if skill_path else None
            if skill_md and skill_md.exists():
                mtime = skill_md.stat().st_mtime
            seen[skill_id] = {
                "id": skill_id,
                "name": skill_info.get("name", skill_id),
                "description": skill_info.get("description", ""),
                "source": source,
                "path": skill_path,
                "managed": True,
                "mtime": mtime,
            }

        # 2. 扫描各 agent 目录下已有的 skill（包括 ln 和实体目录）
        for agent in agents:
            for skills_dir_str in normalize_skills_dirs(agent):
                skills_dir = Path(skills_dir_str)
                if not skills_dir.is_dir():
                    continue
                for item in skills_dir.iterdir():
                    if not item.is_dir():
                        continue
                    skill_id = item.name
                    if skill_id in seen:
                        continue
                    if is_excluded(skill_id, global_exclude):
                        continue
                    # 解析 SKILL.md（跟随 ln）
                    real_path = item.resolve() if item.is_symlink() else item
                    if not (real_path / "SKILL.md").exists():
                        continue
                    meta = parse_skill_md(str(real_path))
                    source = infer_source(str(real_path), hub_path, agents)
                    # 判断是否已归聚：实体路径在 hub_path 下，或在 config.skills 中记录
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

        # 3. 扫描中央仓库下的 skill
        # 先构建已有 skill 的实际路径集合，用于去重
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
                # 基于实际路径去重：如果该路径已被其他 skill_id 记录，跳过
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

        # 4. 为每个 skill 计算各 agent 的启用状态
        #    "origin" = 来源归属方（实体目录或 config 中记录了 origin_agent）
        #    "linked" = symlink（已启用，从中央仓库链接）
        #    false = 不存在
        result = []
        for skill_id, info in sorted(seen.items()):
            # 从 config.skills 中读取 origin_agent 记录
            skill_cfg = managed_skills.get(skill_id, {})
            origin_agent_id = skill_cfg.get("origin_agent")
            agent_status = {}
            for agent in agents:
                status = False
                for d in normalize_skills_dirs(agent):
                    link_path = Path(d) / skill_id
                    if link_path.is_symlink():
                        status = "linked"
                        break
                    elif link_path.is_dir():
                        status = "origin"
                        break
                # 如果 config 记录了 origin_agent，该 agent 有连接时显示 origin
                if origin_agent_id == agent["id"] and status in ("linked",):
                    status = "origin"
                # 如果是实体目录，自动记录 origin_agent（首次发现）
                if status == "origin" and not origin_agent_id:
                    origin_agent_id = agent["id"]
                agent_status[agent["id"]] = status
            info["agents"] = agent_status
            info["origin_agent"] = origin_agent_id
            result.append(info)

        self.send_json(result)

    def _find_skill_real_path(self, skill_id, config):
        """查找 skill 的实际路径：先查配置，再扫描各 agent 目录和中央仓库"""
        skills = config.get("skills", {})
        if skill_id in skills and skills[skill_id].get("path"):
            return Path(skills[skill_id]["path"])
        # 扫描各 agent 目录
        for agent in config.get("agents", []):
            for d in normalize_skills_dirs(agent):
                candidate = Path(d) / skill_id
                if candidate.exists():
                    real = candidate.resolve() if candidate.is_symlink() else candidate
                    return real
        # 扫描中央仓库
        hub_candidate = Path(config["hub_path"]) / skill_id
        if hub_candidate.exists():
            return hub_candidate
        return None

    def handle_toggle_skill(self, skill_id):
        """POST /api/skills/<id>/toggle - 启用/禁用 skill"""
        config = self.get_config_or_uninit()
        if not config:
            self.send_error_json("系统未初始化")
            return
        body = self.read_body()
        agent_id = body.get("agent_id", "")
        if not agent_id:
            self.send_error_json("缺少 agent_id")
            return
        hub_path = config["hub_path"]
        agents = config.get("agents", [])

        # 找到目标 agent
        target_agent = None
        for a in agents:
            if a["id"] == agent_id:
                target_agent = a
                break
        if not target_agent:
            self.send_error_json(f"Agent '{agent_id}' 不存在")
            return

        # 动态查找 skill 的实际路径
        skill_real_path = self._find_skill_real_path(skill_id, config)
        if not skill_real_path:
            self.send_error_json(f"Skill '{skill_id}' 不存在")
            return

        # 在所有目录中查找已存在的 symlink 或实体目录
        agent_dirs = normalize_skills_dirs(target_agent)
        existing_link_path = None
        existing_is_symlink = False
        existing_is_dir = False
        for d in agent_dirs:
            candidate = Path(d) / skill_id
            if candidate.is_symlink():
                existing_link_path = candidate
                existing_is_symlink = True
                break
            elif candidate.is_dir():
                existing_link_path = candidate
                existing_is_dir = True
                break

        batch_id = f"toggle_{uuid4().hex[:8]}"

        if existing_is_symlink:
            # 禁用：删除符号链接
            existing_link_path.unlink()
            append_log(hub_path, batch_id, "unlink", skill_id, {
                "agent_id": agent_id,
                "link_path": str(existing_link_path),
                "target": str(skill_real_path),
            })
            action_done = "disabled"
        elif existing_is_dir:
            # origin 反勾选：把实体目录移到 hub，记录 origin_agent
            hub_dest = Path(hub_path) / skill_id
            if hub_dest.exists():
                self.send_error_json(f"中央仓库已存在 '{skill_id}'，无法移入")
                return
            import shutil
            shutil.move(str(existing_link_path), str(hub_dest))
            # 记录 origin_agent 到 config.skills
            managed_skills = config.setdefault("skills", {})
            skill_cfg = managed_skills.setdefault(skill_id, {})
            skill_cfg["origin_agent"] = agent_id
            skill_cfg["path"] = str(hub_dest)
            if not skill_cfg.get("source"):
                skill_cfg["source"] = "自研"
            save_config(config)
            append_log(hub_path, batch_id, "unlink_origin", skill_id, {
                "agent_id": agent_id,
                "from_path": str(existing_link_path),
                "to_path": str(hub_dest),
            })
            action_done = "disabled"
        else:
            # 启用：在第一个目录下创建符号链接
            link_path = Path(agent_dirs[0]) / skill_id
            link_path.parent.mkdir(parents=True, exist_ok=True)
            os.symlink(str(skill_real_path), str(link_path))
            append_log(hub_path, batch_id, "link", skill_id, {
                "agent_id": agent_id,
                "link_path": str(link_path),
                "target": str(skill_real_path),
            })
            action_done = "enabled"

        self.send_json({"ok": True, "action": action_done, "skill_id": skill_id, "agent_id": agent_id})

    def handle_scan(self):
        """POST /api/scan - 扫描各 agent 目录发现新 skill"""
        config = self.get_config_or_uninit()
        if not config:
            self.send_error_json("系统未初始化")
            return
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

                    # 跳过已是符号链接的
                    if item.is_symlink():
                        report["skipped"].append({"name": skill_name, "reason": "symlink", "agent": agent["id"]})
                        continue

                    # 跳过排除名单中的
                    if is_excluded(skill_name, global_exclude):
                        report["skipped"].append({"name": skill_name, "reason": "excluded", "agent": agent["id"]})
                        continue

                    # 必须包含 SKILL.md
                    if not (item / "SKILL.md").exists():
                        report["skipped"].append({"name": skill_name, "reason": "no SKILL.md", "agent": agent["id"]})
                        continue

                    meta = parse_skill_md(str(item))

                    # 已在中央仓库管理
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

        # 同时扫描中央仓库自身
        hub_dir = Path(hub_path)
        if hub_dir.is_dir():
            for item in hub_dir.iterdir():
                if not item.is_dir() or item.name.startswith("."):
                    continue
                if not (item / "SKILL.md").exists():
                    continue
                skill_name = item.name
                if skill_name in skills:
                    continue
                if is_excluded(skill_name, global_exclude):
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

        self.send_json(report)

    def handle_gather(self):
        """POST /api/gather - 执行归聚"""
        config = self.get_config_or_uninit()
        if not config:
            self.send_error_json("系统未初始化")
            return
        body = self.read_body()
        skill_list = body.get("skills", [])
        if not skill_list:
            self.send_error_json("缺少 skills 列表")
            return

        hub_path = config["hub_path"]
        agents = config.get("agents", [])
        skills = config.get("skills", {})
        batch_id = f"gather_{uuid4().hex[:8]}"
        results = []

        for item in skill_list:
            skill_name = item.get("name", "")
            from_path = item.get("from", "")
            agent_id = item.get("agent_id", "")

            if not skill_name or not from_path:
                results.append({"name": skill_name, "status": "error", "message": "缺少 name 或 from"})
                continue

            src = Path(from_path)
            dest = Path(hub_path) / skill_name

            if not src.exists():
                results.append({"name": skill_name, "status": "error", "message": f"源路径不存在: {from_path}"})
                continue

            if dest.exists():
                results.append({"name": skill_name, "status": "error", "message": f"目标已存在: {dest}"})
                continue

            try:
                # mv 到中央仓库
                shutil.move(str(src), str(dest))
                # 在原位创建符号链接
                os.symlink(str(dest), str(src))

                # 解析元信息
                meta = parse_skill_md(str(dest))
                source = infer_source(str(dest), hub_path, agents)

                # 更新配置
                skill_agents = [agent_id] if agent_id and agent_id != "_hub" else []
                skills[skill_name] = {
                    "name": meta.get("name", skill_name),
                    "description": meta.get("description", ""),
                    "path": str(dest),
                    "source": source,
                    "agents": skill_agents,
                }

                # 记录日志
                append_log(hub_path, batch_id, "gather", skill_name, {
                    "from": from_path,
                    "to": str(dest),
                    "agent_id": agent_id,
                    "link_created": str(src),
                })

                results.append({"name": skill_name, "status": "ok"})
            except Exception as e:
                results.append({"name": skill_name, "status": "error", "message": str(e)})

        config["skills"] = skills
        save_config(config)
        self.send_json({"batch_id": batch_id, "results": results})

    def handle_sync(self):
        """POST /api/sync - 全量同步 ln 状态"""
        config = self.get_config_or_uninit()
        if not config:
            self.send_error_json("系统未初始化")
            return
        hub_path = config["hub_path"]
        agents = config.get("agents", [])
        skills = config.get("skills", {})
        batch_id = f"sync_{uuid4().hex[:8]}"

        report = {"created": [], "orphaned": [], "broken": []}

        for skill_id, skill_info in skills.items():
            skill_path = Path(skill_info["path"])
            enabled_agents = skill_info.get("agents", [])

            # 检查 skill 本体是否存在
            if not skill_path.exists():
                report["broken"].append({"skill": skill_id, "path": str(skill_path), "reason": "skill目录不存在"})
                continue

            for agent in agents:
                agent_dirs = normalize_skills_dirs(agent)
                should_exist = agent["id"] in enabled_agents

                if should_exist:
                    # 检查是否已存在于任一目录
                    exists_anywhere = any((Path(d) / skill_id).exists() for d in agent_dirs)
                    if not exists_anywhere:
                        # 缺少的 ln 补建（在第一个目录下创建）
                        link_path = Path(agent_dirs[0]) / skill_id
                        link_path.parent.mkdir(parents=True, exist_ok=True)
                        os.symlink(str(skill_path), str(link_path))
                        append_log(hub_path, batch_id, "link", skill_id, {
                            "agent_id": agent["id"],
                            "link_path": str(link_path),
                            "target": str(skill_path),
                            "reason": "sync_create",
                        })
                        report["created"].append({"skill": skill_id, "agent": agent["id"], "link": str(link_path)})
                else:
                    # 检查各目录下是否有多余的 symlink
                    for d in agent_dirs:
                        link_path = Path(d) / skill_id
                        if link_path.is_symlink():
                            target = os.readlink(str(link_path))
                            if str(skill_path) == target or str(skill_path.resolve()) == str(Path(target).resolve()):
                                report["orphaned"].append({"skill": skill_id, "agent": agent["id"], "link": str(link_path)})

                # 断链检测（检查所有目录）
                for d in agent_dirs:
                    link_path = Path(d) / skill_id
                    if link_path.is_symlink() and not Path(os.readlink(str(link_path))).exists():
                        report["broken"].append({"skill": skill_id, "agent": agent["id"], "link": str(link_path), "reason": "断链"})

        self.send_json({"batch_id": batch_id, "report": report})

    def handle_scan_sync(self):
        """POST /api/scan-sync - 合并扫描+同步：先扫描发现新 skill，再同步 ln 状态"""
        # 复用 scan 和 sync 逻辑，返回合并报告
        config = self.get_config_or_uninit()
        if not config:
            self.send_error_json("系统未初始化")
            return
        # 先做 sync 检查
        hub_path = config["hub_path"]
        agents = config.get("agents", [])
        skills = config.get("skills", {})
        sync_created = 0
        sync_broken = 0
        for skill_id, skill_info in skills.items():
            skill_path = Path(skill_info.get("path", ""))
            if not skill_path.exists():
                sync_broken += 1
                continue
            for agent in agents:
                agent_dirs = normalize_skills_dirs(agent)
                agent_enabled = agent["id"] in skill_info.get("agents", [])
                if agent_enabled:
                    exists_anywhere = any((Path(d) / skill_id).exists() for d in agent_dirs)
                    if not exists_anywhere:
                        link_path = Path(agent_dirs[0]) / skill_id
                        link_path.parent.mkdir(parents=True, exist_ok=True)
                        os.symlink(str(skill_path), str(link_path))
                        sync_created += 1
        # 然后做 scan：构建完整的已知 skill 集合（config + hub目录 + 各agent目录所有已有skill）
        global_exclude = config.get("global_exclude", [])
        new_discovered = []
        seen_names = set(skills.keys())
        # hub 目录里已有的
        hub_dir = Path(hub_path)
        if hub_dir.is_dir():
            for p in hub_dir.iterdir():
                if p.is_dir():
                    seen_names.add(p.name)
        # 各 agent 目录里已有的（包括 symlink 和实体目录）都算已知
        for agent in agents:
            for skills_dir_str in normalize_skills_dirs(agent):
                skills_dir = Path(skills_dir_str)
                if not skills_dir.is_dir():
                    continue
                for item in skills_dir.iterdir():
                    if item.is_dir():
                        seen_names.add(item.name)
        # 只有全新的（不在任何已知集合里的）才算新发现
        for agent in agents:
            for skills_dir_str in normalize_skills_dirs(agent):
                skills_dir = Path(skills_dir_str)
                if not skills_dir.is_dir():
                    continue
                for item in skills_dir.iterdir():
                    if not item.is_dir() or item.is_symlink():
                        continue
                    skill_name = item.name
                    if skill_name in seen_names:
                        continue
                    if is_excluded(skill_name, global_exclude):
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
        self.send_json({
            "new_discovered": new_discovered,
            "sync_created": sync_created,
            "sync_broken": sync_broken,
        })

    def handle_get_logs(self, batch_id=None):
        """GET /api/logs"""
        config = self.get_config_or_uninit()
        if not config:
            self.send_json([])
            return
        logs = read_logs(config["hub_path"], batch_id)
        self.send_json(logs)

    def handle_rollback_batch(self, batch_id):
        """POST /api/logs/<batch_id>/rollback - 回滚整个批次"""
        config = self.get_config_or_uninit()
        if not config:
            self.send_error_json("系统未初始化")
            return
        hub_path = config["hub_path"]
        logs = read_logs(hub_path, batch_id)
        # 按时间倒序回滚
        logs.sort(key=lambda x: x["ts"], reverse=True)

        rolled = []
        errors = []
        for entry in logs:
            if entry.get("rolled_back") or not entry.get("reversible"):
                continue
            result = self._execute_rollback(entry, config)
            if result["ok"]:
                update_log_entry(hub_path, entry["id"], {"rolled_back": True})
                rolled.append(entry["id"])
            else:
                errors.append({"id": entry["id"], "error": result["error"]})

        save_config(config)
        self.send_json({"rolled_back": rolled, "errors": errors})

    def handle_undo_single(self, log_id):
        """POST /api/logs/<id>/undo - 回滚单条"""
        config = self.get_config_or_uninit()
        if not config:
            self.send_error_json("系统未初始化")
            return
        hub_path = config["hub_path"]
        logs = read_logs(hub_path)
        target = None
        for entry in logs:
            if entry["id"] == log_id:
                target = entry
                break
        if not target:
            self.send_error_json(f"日志 '{log_id}' 不存在", 404)
            return
        if target.get("rolled_back"):
            self.send_error_json("该操作已回滚")
            return
        if not target.get("reversible"):
            self.send_error_json("该操作不可回滚")
            return

        result = self._execute_rollback(target, config)
        if result["ok"]:
            update_log_entry(hub_path, log_id, {"rolled_back": True})
            save_config(config)
            self.send_json({"ok": True, "rolled_back": log_id})
        else:
            self.send_error_json(result["error"])

    def _execute_rollback(self, entry, config):
        """执行单条回滚操作"""
        action = entry.get("action")
        detail = entry.get("detail", {})
        skill_id = entry.get("skill", "")
        skills = config.get("skills", {})

        try:
            if action == "gather":
                # 归聚回滚：将 skill 从中央仓库移回原位
                dest = detail.get("to", "")
                src = detail.get("from", "")
                link_at_src = Path(src)
                # 删除原位的符号链接
                if link_at_src.is_symlink():
                    link_at_src.unlink()
                # 移回
                if Path(dest).exists():
                    shutil.move(dest, src)
                # 从配置中移除
                skills.pop(skill_id, None)
                config["skills"] = skills

            elif action == "link":
                # 创建链接的回滚：删除链接
                link_path = detail.get("link_path", "")
                if Path(link_path).is_symlink():
                    Path(link_path).unlink()
                # 更新配置中的 agents 列表
                agent_id = detail.get("agent_id", "")
                if skill_id in skills:
                    agent_list = skills[skill_id].get("agents", [])
                    if agent_id in agent_list:
                        agent_list.remove(agent_id)
                    skills[skill_id]["agents"] = agent_list
                    config["skills"] = skills

            elif action == "unlink":
                # 删除链接的回滚：重建链接
                link_path = detail.get("link_path", "")
                target = detail.get("target", "")
                if not Path(link_path).exists() and Path(target).exists():
                    Path(link_path).parent.mkdir(parents=True, exist_ok=True)
                    os.symlink(target, link_path)
                # 更新配置
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
        except Exception as e:
            return {"ok": False, "error": str(e)}


    # ------ MCP 处理函数 ------

    def handle_get_mcp(self):
        """GET /api/mcp — 列出所有 MCP（已归聚 + 各 Agent 中未归聚的）及各 Agent 状态"""
        config = self.get_config_or_uninit()
        if not config:
            self.send_json({"mcps": [], "agents": []})
            return
        hub_path = config.get("hub_path", get_default_hub_path())
        agents = config.get("agents", [])
        # 1. 已归聚到 Hub 的
        managed = load_all_mcp(hub_path)
        managed_names = {m["name"] for m in managed}
        # 2. 各 Agent 配置文件中尚未归聚的
        unmanaged = scan_unmanaged_mcp(agents, managed_names)
        # 3. 统一计算 agent_status
        all_mcps = managed + unmanaged
        # 预读各 agent 的 mcp 配置（避免重复 IO）
        agent_mcp_cache = {a["id"]: read_agent_mcp_config(a) for a in agents}
        for mcp in all_mcps:
            mcp["agent_status"] = {}
            for agent in agents:
                mcp["agent_status"][agent["id"]] = mcp["name"] in agent_mcp_cache[agent["id"]]
        self.send_json({
            "mcps": all_mcps,
            "agents": [{"id": a["id"], "name": a["name"]} for a in agents],
        })

    def handle_gather_mcp(self):
        """POST /api/mcp/gather — 从某个 Agent 归聚一个 MCP 到 Hub
        body: {name: str, source_agent_id: str}
        """
        config = self.get_config_or_uninit()
        if not config:
            self.send_error_json("未初始化", 400)
            return
        body = self.read_body()
        name = body.get("name", "").strip()
        source_agent_id = body.get("source_agent_id", "").strip()
        if not name or not source_agent_id:
            self.send_error_json("缺少 name 或 source_agent_id", 400)
            return
        hub_path = config.get("hub_path", get_default_hub_path())
        agents = config.get("agents", [])
        source_agent = next((a for a in agents if a["id"] == source_agent_id), None)
        if not source_agent:
            self.send_error_json(f"Agent '{source_agent_id}' 不存在", 404)
            return
        agent_mcps = read_agent_mcp_config(source_agent)
        raw_cfg = agent_mcps.get(name)
        if raw_cfg is None:
            self.send_error_json(f"MCP '{name}' 在 Agent '{source_agent_id}' 中不存在", 404)
            return
        std = parse_agent_mcp_to_standard(name, raw_cfg)
        if not std:
            self.send_error_json("无法解析该 MCP 配置", 400)
            return
        std["created_at"] = datetime.now(timezone.utc).isoformat()
        std["gathered_from"] = source_agent_id
        save_mcp(hub_path, std)
        batch_id = f"mcp_gather_{uuid4().hex[:8]}"
        append_log(hub_path, batch_id, "mcp_gather", name, {
            "source_agent_id": source_agent_id,
            "type": std.get("type", "unknown"),
        }, reversible=False)
        self.send_json({"success": True, "mcp": std})

    def handle_add_mcp(self):
        """POST /api/mcp — 手动添加 MCP"""
        config = self.get_config_or_uninit()
        if not config:
            self.send_error_json("未初始化", 400)
            return
        body = self.read_body()
        hub_path = config.get("hub_path", get_default_hub_path())
        mcp_data = {
            "name": body.get("name", "").strip(),
            "type": body.get("type", "stdio"),
            "description": body.get("description", ""),
            "created_at": datetime.now(timezone.utc).isoformat(),
        }
        if not mcp_data["name"]:
            self.send_error_json("名称不能为空", 400)
            return
        mcp_type = mcp_data["type"]
        if mcp_type == "stdio":
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
        agents = config.get("agents", [])
        for agent in agents:
            if agent["id"] in target_agents:
                adapted = adapt_mcp_for_agent(mcp_data, agent["id"])
                write_agent_mcp_entry(agent, mcp_data["name"], adapted)
        self.send_json({"success": True, "mcp": mcp_data})

    def handle_edit_mcp(self, mcp_name):
        """PUT /api/mcp/{name} — 编辑 MCP"""
        config = self.get_config_or_uninit()
        if not config:
            self.send_error_json("未初始化", 400)
            return
        body = self.read_body()
        hub_path = config.get("hub_path", get_default_hub_path())
        mcp_dir = get_mcp_dir(hub_path)
        filepath = mcp_dir / f"{mcp_name}.json"
        if not filepath.exists():
            self.send_error_json("MCP 不存在", 404)
            return
        with open(filepath, "r", encoding="utf-8") as fp:
            mcp_data = json.load(fp)
        for key in ["type", "description", "command", "args", "env", "url", "headers"]:
            if key in body:
                mcp_data[key] = body[key]
        save_mcp(hub_path, mcp_data)
        self.send_json({"success": True, "mcp": mcp_data})

    def handle_delete_mcp(self, mcp_name):
        """DELETE /api/mcp/{name} — 彻底删除 MCP"""
        config = self.get_config_or_uninit()
        if not config:
            self.send_error_json("未初始化", 400)
            return
        hub_path = config.get("hub_path", get_default_hub_path())
        agents = config.get("agents", [])
        for agent in agents:
            remove_agent_mcp_entry(agent, mcp_name)
        deleted = delete_mcp(hub_path, mcp_name)
        if deleted:
            batch_id = f"mcp_delete_{uuid4().hex[:8]}"
            append_log(hub_path, batch_id, "mcp_delete", mcp_name, {}, reversible=False)
        self.send_json({"success": deleted})

    def handle_delete_skill(self, skill_id):
        """DELETE /api/skills/{id} — 从 Hub 删除 skill"""
        import shutil
        config = self.get_config_or_uninit()
        if not config:
            self.send_error_json("未初始化", 400)
            return
        hub_path = Path(config.get("hub_path", get_default_hub_path()))
        skill_dir = hub_path / skill_id
        if not skill_dir.exists():
            self.send_error_json(f"Skill '{skill_id}' 不存在", 404)
            return
        # 删除整个 skill 目录
        shutil.rmtree(skill_dir)
        self.send_json({"success": True})

    def handle_toggle_mcp(self, mcp_name):
        """POST /api/mcp/{name}/toggle — 切换启用/禁用"""
        config = self.get_config_or_uninit()
        if not config:
            self.send_error_json("未初始化", 400)
            return
        body = self.read_body()
        agent_id = body.get("agent_id", "")
        enabled = body.get("enabled", False)
        hub_path = config.get("hub_path", get_default_hub_path())
        agents = config.get("agents", [])
        agent = next((a for a in agents if a["id"] == agent_id), None)
        if not agent:
            self.send_error_json(f"Agent '{agent_id}' 不存在", 404)
            return
        if enabled:
            mcp_dir = get_mcp_dir(hub_path)
            filepath = mcp_dir / f"{mcp_name}.json"
            if not filepath.exists():
                self.send_error_json(f"MCP '{mcp_name}' 不存在", 404)
                return
            with open(filepath, "r", encoding="utf-8") as fp:
                mcp_data = json.load(fp)
            adapted = adapt_mcp_for_agent(mcp_data, agent_id)
            write_agent_mcp_entry(agent, mcp_name, adapted)
        else:
            remove_agent_mcp_entry(agent, mcp_name)
        batch_id = f"mcp_toggle_{uuid4().hex[:8]}"
        action = "mcp_enable" if enabled else "mcp_disable"
        append_log(hub_path, batch_id, action, mcp_name, {"agent_id": agent_id}, reversible=False)
        self.send_json({"success": True, "mcp_name": mcp_name, "agent_id": agent_id, "enabled": enabled})

    def handle_test_mcp(self, mcp_name):
        """POST /api/mcp/{name}/test — 测试连通性"""
        config = self.get_config_or_uninit()
        if not config:
            self.send_error_json("未初始化", 400)
            return
        hub_path = config.get("hub_path", get_default_hub_path())
        mcp_dir = get_mcp_dir(hub_path)
        filepath = mcp_dir / f"{mcp_name}.json"
        if not filepath.exists():
            self.send_error_json(f"MCP '{mcp_name}' 不存在", 404)
            return
        with open(filepath, "r", encoding="utf-8") as fp:
            mcp_data = json.load(fp)
        result = test_mcp_connectivity(mcp_data)
        # 连通成功且描述为空时，尝试获取工具列表自动填充描述
        if result.get("status") == "ok" and not mcp_data.get("description"):
            auto_desc = fetch_mcp_tools_description(mcp_data)
            if auto_desc:
                mcp_data["description"] = auto_desc
                save_mcp(hub_path, mcp_data)
                result["auto_description"] = auto_desc
        self.send_json(result)

    def handle_upload_skill(self):
        """POST /api/skills/upload — 上传 .zip skill 包"""
        import zipfile
        import tempfile
        import shutil
        import re

        config = self.get_config_or_uninit()
        if not config:
            self.send_error_json("未初始化", 400)
            return
        hub_path = Path(config.get("hub_path", get_default_hub_path()))

        # 解析 multipart/form-data
        content_type = self.headers.get("Content-Type", "")
        if "multipart/form-data" not in content_type:
            self.send_error_json("需要 multipart/form-data", 400)
            return

        # 提取 boundary
        boundary = None
        for part in content_type.split(";"):
            if "boundary=" in part:
                boundary = part.split("boundary=")[1].strip().strip('"')
                break
        if not boundary:
            self.send_error_json("缺少 boundary", 400)
            return

        # 读取 body
        content_length = int(self.headers.get("Content-Length", 0))
        body = self.rfile.read(content_length)

        # 解析 multipart，提取 file
        boundary_bytes = boundary.encode()
        parts = body.split(boundary_bytes)
        file_data = None
        filename = None

        for part in parts:
            if not part or part == b"--" or part == b"--\r\n":
                continue
            # 找 header
            header_end = part.find(b"\r\n\r\n")
            if header_end == -1:
                continue
            headers = part[:header_end].decode("utf-8", errors="ignore")
            data = part[header_end + 4:]
            # 去掉尾部 \r\n
            if data.endswith(b"\r\n"):
                data = data[:-2]
            if "filename=" in headers:
                # 提取 filename
                match = re.search(r'filename="([^"]+)"', headers)
                if match:
                    filename = match.group(1)
                    file_data = data
                    break

        if not file_data or not filename:
            self.send_error_json("未找到上传文件", 400)
            return

        if not filename.endswith(".zip"):
            self.send_error_json("只支持 .zip 文件", 400)
            return

        # 临时目录解包
        tmp_dir = Path(tempfile.mkdtemp())
        try:
            zip_path = tmp_dir / filename
            with open(zip_path, "wb") as fp:
                fp.write(file_data)

            with zipfile.ZipFile(zip_path, "r") as zf:
                zf.extractall(tmp_dir)

            # 找 skill 根目录
            # 情况A: zip 内直接是文件（SKILL.md, scripts/...）
            # 情况B: zip 内有唯一子目录
            extracted_files = list(tmp_dir.iterdir())
            skill_root = None
            skill_name = None

            # 排除 zip 本身 + macOS 元数据
            extracted_files = [
                f for f in extracted_files
                if f.name != filename and f.name != "__MACOSX" and f.name != ".DS_Store"
            ]

            if len(extracted_files) == 1 and extracted_files[0].is_dir():
                # 情况B: 单子目录
                skill_root = extracted_files[0]
                skill_name = skill_root.name
            else:
                # 情况A: 根目录就是 skill 目录，用 zip 文件名（去 .zip）
                skill_root = tmp_dir
                skill_name = filename[:-4]  # 去掉 .zip

            # 规范检查
            skill_md_path = skill_root / "SKILL.md"
            if not skill_md_path.exists():
                shutil.rmtree(tmp_dir)
                self.send_error_json("缺少 SKILL.md 文件", 400)
                return

            skill_md_content = skill_md_path.read_text(encoding="utf-8")
            # 解析 frontmatter
            if not skill_md_content.startswith("---"):
                shutil.rmtree(tmp_dir)
                self.send_error_json("SKILL.md 缺少 frontmatter（需要以 --- 开头）", 400)
                return

            # 提取 frontmatter
            parts = skill_md_content.split("---")
            if len(parts) < 3:
                shutil.rmtree(tmp_dir)
                self.send_error_json("frontmatter 格式错误（需要 --- 包围）", 400)
                return

            frontmatter_text = parts[1].strip()
            frontmatter = {}
            for line in frontmatter_text.split("\n"):
                if ":" in line:
                    k, v = line.split(":", 1)
                    frontmatter[k.strip()] = v.strip().strip('"').strip("'")

            if "name" not in frontmatter or not frontmatter["name"]:
                shutil.rmtree(tmp_dir)
                self.send_error_json("frontmatter 缺少 name 字段", 400)
                return

            if "description" not in frontmatter or not frontmatter["description"]:
                shutil.rmtree(tmp_dir)
                self.send_error_json("frontmatter 缺少 description 字段", 400)
                return

            skill_name = frontmatter["name"]

            # 检查名称冲突
            target_dir = hub_path / skill_name
            if target_dir.exists():
                shutil.rmtree(tmp_dir)
                self.send_error_json(f"已存在同名 skill: {skill_name}", 400)
                return

            # 移动到 hub
            if skill_root == tmp_dir:
                # 情况A: 需要创建目标目录再移动文件
                target_dir.mkdir(parents=True, exist_ok=True)
                for f in tmp_dir.iterdir():
                    if f.name != filename:
                        shutil.move(str(f), str(target_dir / f.name))
            else:
                # 情况B: 直接移动子目录
                shutil.move(str(skill_root), str(target_dir))

            shutil.rmtree(tmp_dir)

            # 返回成功
            self.send_json({
                "success": True,
                "skill": {
                    "name": skill_name,
                    "description": frontmatter.get("description", "")
                }
            })

        except zipfile.BadZipFile:
            shutil.rmtree(tmp_dir)
            self.send_error_json("zip 文件格式错误", 400)
        except Exception as e:
            shutil.rmtree(tmp_dir)
            self.send_error_json(f"处理失败: {e}", 500)


# ============================================================
# 启动入口
# ============================================================

def _startup_network_check(port):
    """启动时网络环境自检：检测系统代理、端口可用性"""
    issues = []

    # 1. 检查系统 HTTP/HTTPS 代理
    proxy_env_vars = {
        "http_proxy": os.environ.get("http_proxy", ""),
        "https_proxy": os.environ.get("https_proxy", ""),
        "HTTP_PROXY": os.environ.get("HTTP_PROXY", ""),
        "HTTPS_PROXY": os.environ.get("HTTPS_PROXY", ""),
        "ALL_PROXY": os.environ.get("ALL_PROXY", ""),
        "all_proxy": os.environ.get("all_proxy", ""),
        "NO_PROXY": os.environ.get("NO_PROXY", os.environ.get("no_proxy", "")),
    }
    active_proxies = {k: v for k, v in proxy_env_vars.items() if v and k != "NO_PROXY"}
    no_proxy = proxy_env_vars["NO_PROXY"]

    if active_proxies:
        # 检查 localhost 是否在 NO_PROXY 中
        localhost_excluded = any(
            host in no_proxy.split(",")
            for host in ["localhost", "127.0.0.1", ".local"]
        ) if no_proxy else False

        issues.append({
            "type": "proxy_env",
            "message": f"检测到系统代理: {active_proxies}",
            "localhost_excluded": localhost_excluded,
        })

    # 2. 端口绑定测试（非连接测试，因为 serve_forever 尚未启动）
    import socket as sock_mod
    port_available = False
    port_error = None
    try:
        s = sock_mod.socket(sock_mod.AF_INET, sock_mod.SOCK_STREAM)
        s.setsockopt(sock_mod.SOL_SOCKET, sock_mod.SO_REUSEADDR, 1)
        s.bind(("127.0.0.1", port))
        s.close()
        port_available = True
    except Exception as e:
        port_error = str(e)
        issues.append({
            "type": "port_unavailable",
            "message": f"端口 {port} 被占用或不可绑定",
            "error": port_error,
        })

    return {
        "port_available": port_available,
        "port_error": port_error,
        "active_proxies": active_proxies,
        "no_proxy": no_proxy,
        "issues": issues,
    }


def main():
    """启动 Tool Hub 服务"""
    print(f"🚀 Tool Hub Server 启动中...")
    print(f"   端口: {PORT}")
    print(f"   地址: http://localhost:{PORT}")

    # 网络环境自检
    print()
    print(f"   🔍 网络环境自检...")
    net_check = _startup_network_check(PORT)

    if net_check["active_proxies"]:
        no_proxy_status = "localhost 在 NO_PROXY 中" if any(
            i.get("localhost_excluded") for i in net_check["issues"] if i["type"] == "proxy_env"
        ) else "localhost 不在 NO_PROXY 中"
        print(f"\n   ⚠️  检测到系统代理变量:")
        for k, v in net_check["active_proxies"].items():
            print(f"      {k}={v}")
        print(f"      NO_PROXY={net_check['no_proxy'] or '(未设置)'}")
        print(f"      👉 {no_proxy_status}")
        print(f"      💡 如果工具（curl/Agent）通过代理访问本服务，POST 请求可能失败。")
        print(f"      建议：curl 使用 --noproxy='localhost,127.0.0.1' 或设置 NO_PROXY。")

    if not net_check["port_available"]:
        print(f"\n   ❌ 端口 {PORT} 不可用: {net_check['port_error']}")
        print(f"      💡 请检查端口是否被占用或需要管理员权限。")
    else:
        print(f"   ✅ 端口 {PORT} 可用")

    print()

    # 启动时自动补全已配 Agent 的缺失字段（mcp_config_path 等）
    try:
        config = load_config()
        if config and migrate_config_with_presets(config):
            save_config(config)
            print(f"   ✅ 已自动补全 Agent 缺失字段（mcp_config_path 等）")
    except Exception as e:
        print(f"   ⚠️ 启动迁移失败（不影响服务）: {e}")
    print()

    server = HTTPServer(("0.0.0.0", PORT), SkillHubHandler)

    # 自动打开浏览器
    webbrowser.open(f"http://localhost:{PORT}")

    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n⏹  服务已停止")
        server.shutdown()


if __name__ == "__main__":
    main()
