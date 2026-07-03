import json

from tool_hub.safety import make_backup


class JsonConfigBackend:
    name = "json"

    def read_servers(self, config_path, config_key):
        with open(config_path, "r", encoding="utf-8") as fp:
            data = json.load(fp)
        servers = data.get(config_key, {})
        return servers if isinstance(servers, dict) else {}

    def verify(self, config_path):
        with open(config_path, "r", encoding="utf-8") as fp:
            json.load(fp)
        return True

    def write_server(self, config_path, config_key, mcp_name, mcp_config):
        backup_path = make_backup(config_path)
        with open(config_path, "r", encoding="utf-8") as fp:
            data = json.load(fp)
        if config_key not in data:
            data[config_key] = {}
        data[config_key][mcp_name] = mcp_config
        with open(config_path, "w", encoding="utf-8") as fp:
            json.dump(data, fp, ensure_ascii=False, indent=2)
        self.verify(config_path)
        return backup_path

    def remove_server(self, config_path, config_key, mcp_name):
        with open(config_path, "r", encoding="utf-8") as fp:
            data = json.load(fp)
        servers = data.get(config_key, {})
        if mcp_name not in servers:
            return None, False
        backup_path = make_backup(config_path)
        del servers[mcp_name]
        with open(config_path, "w", encoding="utf-8") as fp:
            json.dump(data, fp, ensure_ascii=False, indent=2)
        self.verify(config_path)
        return backup_path, True

