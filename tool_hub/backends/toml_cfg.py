import ast
import json
import re

from tool_hub.safety import make_backup


def parse_toml_value(raw):
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


def toml_quote(value):
    return json.dumps(str(value), ensure_ascii=False)


def toml_value(value):
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (int, float)):
        return str(value)
    if isinstance(value, list):
        return "[" + ", ".join(toml_value(item) for item in value) + "]"
    return toml_quote(value)


def read_toml_mcp_config(config_path, config_key):
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
            target[key] = parse_toml_value(raw_value)
    return merged


def toml_mcp_sections(config_key, mcp_name, mcp_config):
    lines = [f"[{config_key}.{mcp_name}]"]
    child_tables = {}
    for key, value in mcp_config.items():
        if isinstance(value, dict):
            child_tables[key] = value
        else:
            lines.append(f"{key} = {toml_value(value)}")
    for child_key, child_value in child_tables.items():
        lines.append("")
        lines.append(f"[{config_key}.{mcp_name}.{child_key}]")
        for key, value in child_value.items():
            lines.append(f"{key} = {toml_value(value)}")
    return "\n".join(lines) + "\n"


def remove_toml_mcp_sections(content, config_key, mcp_name):
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


def write_toml_mcp_entry(config_path, config_key, mcp_name, mcp_config):
    content = config_path.read_text(encoding="utf-8")
    content, _ = remove_toml_mcp_sections(content, config_key, mcp_name)
    content = content.rstrip() + "\n\n" + toml_mcp_sections(config_key, mcp_name, mcp_config)
    config_path.write_text(content, encoding="utf-8")
    return True


def remove_toml_mcp_entry(config_path, config_key, mcp_name):
    content = config_path.read_text(encoding="utf-8")
    content, removed = remove_toml_mcp_sections(content, config_key, mcp_name)
    if removed:
        config_path.write_text(content, encoding="utf-8")
    return removed


class TomlConfigBackend:
    name = "toml"

    def read_servers(self, config_path, config_key):
        return read_toml_mcp_config(config_path, config_key)

    def verify(self, config_path):
        read_toml_mcp_config(config_path, "mcp_servers")
        return True

    def write_server(self, config_path, config_key, mcp_name, mcp_config):
        backup_path = make_backup(config_path)
        write_toml_mcp_entry(config_path, config_key, mcp_name, mcp_config)
        self.read_servers(config_path, config_key)
        return backup_path

    def remove_server(self, config_path, config_key, mcp_name):
        content = config_path.read_text(encoding="utf-8")
        _, would_remove = remove_toml_mcp_sections(content, config_key, mcp_name)
        if not would_remove:
            return None, False
        backup_path = make_backup(config_path)
        removed = remove_toml_mcp_entry(config_path, config_key, mcp_name)
        if removed:
            self.read_servers(config_path, config_key)
        return backup_path, removed
