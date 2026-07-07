#!/usr/bin/env python3
"""AgentToolHub Server - 跨 Agent 统一管理台（Skill + MCP）"""

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

from tool_hub import audit as hub_audit
from tool_hub import config_store as hub_config_store
from tool_hub import presets as hub_presets
from tool_hub.backends import toml_cfg as hub_toml_cfg
from tool_hub.errors import ToolHubError
from tool_hub.linking import is_managed_link, resolve_link_or_self
from tool_hub.mcp import adapters as hub_mcp_adapters
from tool_hub.mcp import agent_config as hub_mcp_agent_config
from tool_hub.mcp import runtime as hub_mcp_runtime
from tool_hub.mcp import store as hub_mcp_store
from tool_hub.services.audit import AuditService
from tool_hub.services.agents import AgentService
from tool_hub.services.config import ConfigService
from tool_hub.services.mcp import McpService
from tool_hub.services.skills import SkillService
from tool_hub.services.upload import UploadSkillService
from tool_hub.safety import allow_cors_origin

PORT = 8998
CONFIG_FILENAME = "tool-hub.json"
LOG_FILENAME = ".tool-hub-log.jsonl"

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
            if skill_path.startswith(agent_dir) and not is_managed_link(Path(skill_path)):
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
MCP_ADAPTERS_DIR = Path(__file__).parent / "data" / "mcp-adapters"

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
            init_req = json.dumps({"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {"protocolVersion": "2025-03-26", "capabilities": {}, "clientInfo": {"name": "agent-tool-hub", "version": "1.0"}}}) + "\n"
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
            init_payload = json.dumps({"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {"protocolVersion": "2025-03-26", "capabilities": {}, "clientInfo": {"name": "agent-tool-hub", "version": "1.0"}}}).encode()
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
            payload = json.dumps({"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {"protocolVersion": "2025-03-26", "capabilities": {}, "clientInfo": {"name": "agent-tool-hub-test", "version": "1.0"}}}).encode("utf-8")
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

# Single source of truth for hub-path/config persistence.
get_default_hub_path = hub_config_store.get_default_hub_path
get_saved_hub_path = hub_config_store.get_saved_hub_path
save_hub_path_pointer = hub_config_store.save_hub_path_pointer
load_config = hub_config_store.load_config
save_config = hub_config_store.save_config

AGENT_PRESETS = hub_presets.get_agent_presets()
_resolve_preset_paths = hub_presets.resolve_preset_paths
detect_agents = hub_presets.detect_agents
fill_missing_fields_from_preset = hub_presets.fill_missing_fields_from_preset
migrate_config_with_presets = hub_presets.migrate_config_with_presets

append_log = hub_audit.append_log
read_logs = hub_audit.read_logs
update_log_entry = hub_audit.update_log_entry

MCP_DIR_NAME = hub_mcp_store.MCP_DIR_NAME
MCP_ADAPTERS_DIR = hub_mcp_adapters.MCP_ADAPTERS_DIR
get_mcp_dir = hub_mcp_store.get_mcp_dir
load_all_mcp = hub_mcp_store.load_all_mcp
save_mcp = hub_mcp_store.save_mcp
delete_mcp = hub_mcp_store.delete_mcp
load_adapter = hub_mcp_adapters.load_adapter
parse_agent_mcp_to_standard = hub_mcp_adapters.parse_agent_mcp_to_standard
adapt_mcp_for_agent = hub_mcp_adapters.adapt_mcp_for_agent
_build_raw_config = hub_mcp_adapters.build_raw_config
_get_mcp_config_paths = hub_mcp_agent_config.get_mcp_config_paths
read_agent_mcp_config = hub_mcp_agent_config.read_agent_mcp_config
write_agent_mcp_entry = hub_mcp_agent_config.write_agent_mcp_entry
remove_agent_mcp_entry = hub_mcp_agent_config.remove_agent_mcp_entry
_parse_toml_value = hub_toml_cfg.parse_toml_value
_toml_quote = hub_toml_cfg.toml_quote
_toml_value = hub_toml_cfg.toml_value
_read_toml_mcp_config = hub_toml_cfg.read_toml_mcp_config
_toml_mcp_sections = hub_toml_cfg.toml_mcp_sections
_remove_toml_mcp_sections = hub_toml_cfg.remove_toml_mcp_sections
_write_toml_mcp_entry = hub_toml_cfg.write_toml_mcp_entry
_remove_toml_mcp_entry = hub_toml_cfg.remove_toml_mcp_entry
fetch_mcp_tools_description = hub_mcp_runtime.fetch_mcp_tools_description
test_mcp_connectivity = hub_mcp_runtime.test_mcp_connectivity

AGENT_SERVICE = AgentService()
CONFIG_SERVICE = ConfigService()
MCP_SERVICE = McpService()
SKILL_SERVICE = SkillService()
UPLOAD_SERVICE = UploadSkillService()
AUDIT_SERVICE = AuditService()


class SkillHubHandler(BaseHTTPRequestHandler):
    """AgentToolHub HTTP 请求处理器"""

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
        allowed_origin = allow_cors_origin(
            self.headers.get("Origin"),
            self.server.server_address[0],
            self.server.server_address[1],
        )
        if allowed_origin:
            self.send_header("Access-Control-Allow-Origin", allowed_origin)
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

    def read_raw_body(self):
        """读取原始请求体"""
        length = int(self.headers.get("Content-Length", 0))
        if length == 0:
            return b""
        return self.rfile.read(length)

    def get_config_or_uninit(self):
        """获取配置，未初始化返回 None"""
        config = load_config()  # 自动查找指针文件或默认路径
        return config

    def run_service(self, callback, *args, **kwargs):
        try:
            return callback(*args, **kwargs)
        except ToolHubError as error:
            self.send_error_json(error.message, error.status)
            return None

    # ------ 路由分发 ------

    def do_OPTIONS(self):
        """处理 CORS 预检请求"""
        self.send_response(204)
        allowed_origin = allow_cors_origin(
            self.headers.get("Origin"),
            self.server.server_address[0],
            self.server.server_address[1],
        )
        if allowed_origin:
            self.send_header("Access-Control-Allow-Origin", allowed_origin)
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
        self.send_json(CONFIG_SERVICE.get_config(self.get_config_or_uninit()))

    def handle_put_config(self):
        """PUT /api/config - 更新/初始化配置"""
        result = self.run_service(CONFIG_SERVICE.put_config, self.read_body())
        if result is not None:
            self.send_json(result)

    def handle_get_agents(self):
        """GET /api/agents"""
        self.send_json(CONFIG_SERVICE.list_agents(self.get_config_or_uninit()))

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
        prompt = f"""你现在需要把当前这个 Agent 接入 AgentToolHub。

请你自动检测当前 Agent 的本地配置，并将结果写入 AgentToolHub。

AgentToolHub 信息：
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

6. 优先通过 AgentToolHub API 写入：
   POST http://localhost:{PORT}/api/agents/upsert

   请求体必须使用以下结构：
{json.dumps(schema, ensure_ascii=False, indent=2)}

7. 如果 AgentToolHub API 不可用，则直接修改配置文件：
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
        return AGENT_SERVICE.build_agent_from_body(body, fallback_id=fallback_id)

    def handle_add_agent(self):
        """POST /api/agents"""
        result = self.run_service(AGENT_SERVICE.add_agent, self.get_config_or_uninit(), self.read_body())
        if result is not None:
            self.send_json(result)

    def handle_upsert_agent(self):
        """POST /api/agents/upsert - 新增或更新 Agent，供未知 Agent 自助接入"""
        result = self.run_service(AGENT_SERVICE.upsert_agent, self.get_config_or_uninit(), self.read_body())
        if result is not None:
            self.send_json(result)

    def handle_edit_agent(self, agent_id):
        """PUT /api/agents/<id>"""
        result = self.run_service(AGENT_SERVICE.edit_agent, self.get_config_or_uninit(), agent_id, self.read_body())
        if result is not None:
            self.send_json(result)

    def handle_delete_agent(self, agent_id):
        """DELETE /api/agents/<id>"""
        result = self.run_service(AGENT_SERVICE.delete_agent, self.get_config_or_uninit(), agent_id)
        if result is not None:
            self.send_json(result)

    def handle_get_skills(self):
        """GET /api/skills - 获取所有 skill（已管理 + 各 agent 目录下已有的）"""
        self.send_json(SKILL_SERVICE.list_skills(self.get_config_or_uninit()))

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
                    real = resolve_link_or_self(candidate)
                    return real
        # 扫描中央仓库
        hub_candidate = Path(config["hub_path"]) / skill_id
        if hub_candidate.exists():
            return hub_candidate
        return None

    def handle_toggle_skill(self, skill_id):
        """POST /api/skills/<id>/toggle - 启用/禁用 skill"""
        result = self.run_service(SKILL_SERVICE.toggle_skill, self.get_config_or_uninit(), skill_id, self.read_body())
        if result is not None:
            self.send_json(result)

    def handle_scan(self):
        """POST /api/scan - 扫描各 agent 目录发现新 skill"""
        result = self.run_service(SKILL_SERVICE.scan, self.get_config_or_uninit())
        if result is not None:
            self.send_json(result)

    def handle_gather(self):
        """POST /api/gather - 执行归聚"""
        result = self.run_service(SKILL_SERVICE.gather, self.get_config_or_uninit(), self.read_body())
        if result is not None:
            self.send_json(result)

    def handle_sync(self):
        """POST /api/sync - 全量同步 ln 状态"""
        result = self.run_service(SKILL_SERVICE.sync, self.get_config_or_uninit())
        if result is not None:
            self.send_json(result)

    def handle_scan_sync(self):
        """POST /api/scan-sync - 合并扫描+同步：先扫描发现新 skill，再同步 ln 状态"""
        result = self.run_service(SKILL_SERVICE.scan_sync, self.get_config_or_uninit())
        if result is not None:
            self.send_json(result)

    def handle_get_logs(self, batch_id=None):
        """GET /api/logs"""
        self.send_json(AUDIT_SERVICE.list_logs(self.get_config_or_uninit(), batch_id))

    def handle_rollback_batch(self, batch_id):
        """POST /api/logs/<batch_id>/rollback - 回滚整个批次"""
        result = self.run_service(AUDIT_SERVICE.rollback_batch, self.get_config_or_uninit(), batch_id)
        if result is not None:
            self.send_json(result)

    def handle_undo_single(self, log_id):
        """POST /api/logs/<id>/undo - 回滚单条"""
        result = self.run_service(AUDIT_SERVICE.undo_single, self.get_config_or_uninit(), log_id)
        if result is not None:
            self.send_json(result)


    # ------ MCP 处理函数 ------

    def handle_get_mcp(self):
        """GET /api/mcp — 列出所有 MCP（已归聚 + 各 Agent 中未归聚的）及各 Agent 状态"""
        self.send_json(MCP_SERVICE.list_mcp(self.get_config_or_uninit()))

    def handle_gather_mcp(self):
        """POST /api/mcp/gather — 从某个 Agent 归聚一个 MCP 到 Hub
        body: {name: str, source_agent_id: str}
        """
        result = self.run_service(MCP_SERVICE.gather_mcp, self.get_config_or_uninit(), self.read_body())
        if result is not None:
            self.send_json(result)

    def handle_add_mcp(self):
        """POST /api/mcp — 手动添加 MCP"""
        result = self.run_service(MCP_SERVICE.add_mcp, self.get_config_or_uninit(), self.read_body())
        if result is not None:
            self.send_json(result)

    def handle_edit_mcp(self, mcp_name):
        """PUT /api/mcp/{name} — 编辑 MCP"""
        result = self.run_service(MCP_SERVICE.edit_mcp, self.get_config_or_uninit(), mcp_name, self.read_body())
        if result is not None:
            self.send_json(result)

    def handle_delete_mcp(self, mcp_name):
        """DELETE /api/mcp/{name} — 彻底删除 MCP"""
        result = self.run_service(MCP_SERVICE.delete_mcp, self.get_config_or_uninit(), mcp_name)
        if result is not None:
            self.send_json(result)

    def handle_delete_skill(self, skill_id):
        """DELETE /api/skills/{id} — 从 Hub 删除 skill"""
        result = self.run_service(SKILL_SERVICE.delete_skill, self.get_config_or_uninit(), skill_id)
        if result is not None:
            self.send_json(result)

    def handle_toggle_mcp(self, mcp_name):
        """POST /api/mcp/{name}/toggle — 切换启用/禁用"""
        result = self.run_service(MCP_SERVICE.toggle_mcp, self.get_config_or_uninit(), mcp_name, self.read_body())
        if result is not None:
            self.send_json(result)

    def handle_test_mcp(self, mcp_name):
        """POST /api/mcp/{name}/test — 测试连通性"""
        body = self.read_body()
        fetch_tools = bool(body.get("fetch_tools")) if body else False
        result = self.run_service(MCP_SERVICE.test_mcp, self.get_config_or_uninit(), mcp_name, fetch_tools=fetch_tools)
        if result is not None:
            self.send_json(result)

    def handle_upload_skill(self):
        """POST /api/skills/upload — 上传 .zip skill 包"""
        result = self.run_service(
            UPLOAD_SERVICE.upload,
            self.get_config_or_uninit(),
            dict(self.headers),
            self.read_raw_body(),
        )
        if result is not None:
            self.send_json(result)


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
    """启动 AgentToolHub 服务"""
    print(f"🚀 AgentToolHub Server 启动中...")
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

    server = HTTPServer(("127.0.0.1", PORT), SkillHubHandler)

    # 自动打开浏览器
    webbrowser.open(f"http://localhost:{PORT}")

    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n⏹  服务已停止")
        server.shutdown()


if __name__ == "__main__":
    main()
