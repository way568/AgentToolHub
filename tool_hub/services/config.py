from uuid import uuid4

from tool_hub.audit import append_log
from tool_hub.config_store import get_default_hub_path, load_config, save_config
from tool_hub.presets import detect_agents


class ConfigService:
    def get_config(self, config):
        if config is None:
            return {"initialized": False}
        result = dict(config)
        result["initialized"] = True
        return result

    def put_config(self, body):
        hub_path = body.get("hub_path", get_default_hub_path())
        global_exclude = body.get("global_exclude", [])

        existing = load_config(hub_path)
        if existing:
            existing["hub_path"] = hub_path
            existing["global_exclude"] = global_exclude
            config = existing
        else:
            config = {
                "hub_path": hub_path,
                "global_exclude": global_exclude,
                "agents": detect_agents(),
                "skills": {},
            }

        save_config(config)
        batch_id = f"config_{uuid4().hex[:8]}"
        append_log(
            hub_path,
            batch_id,
            "config",
            "",
            {"action": "update_config", "hub_path": hub_path},
            reversible=False,
        )
        return self.get_config(config)

    def list_agents(self, config):
        if not config:
            return []
        return config.get("agents", [])
