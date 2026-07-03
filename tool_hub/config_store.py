import json
from pathlib import Path

from tool_hub.safety import make_backup


CONFIG_FILENAME = "tool-hub.json"
HUB_PATH_POINTER = Path(__file__).resolve().parents[1] / ".hub-path"


def get_default_hub_path():
    return str(Path.home() / "tool-hub")


def get_saved_hub_path():
    if HUB_PATH_POINTER.exists():
        return HUB_PATH_POINTER.read_text(encoding="utf-8").strip()
    return None


def save_hub_path_pointer(hub_path):
    HUB_PATH_POINTER.write_text(hub_path, encoding="utf-8")


def load_config(hub_path=None):
    if not hub_path:
        hub_path = get_saved_hub_path() or get_default_hub_path()
    config_path = Path(hub_path) / CONFIG_FILENAME
    if not config_path.exists():
        return None
    with open(config_path, "r", encoding="utf-8") as fp:
        return json.load(fp)


def save_config(config):
    hub_path = config.get("hub_path", get_default_hub_path())
    Path(hub_path).mkdir(parents=True, exist_ok=True)
    config_path = Path(hub_path) / CONFIG_FILENAME
    if config_path.exists():
        make_backup(config_path)
    with open(config_path, "w", encoding="utf-8") as fp:
        json.dump(config, fp, ensure_ascii=False, indent=2)
    with open(config_path, "r", encoding="utf-8") as fp:
        json.load(fp)
    save_hub_path_pointer(hub_path)
