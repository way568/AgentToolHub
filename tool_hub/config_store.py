import json
import os
import tempfile
from pathlib import Path

from tool_hub.safety import make_backup

try:
    import fcntl
except ImportError:  # pragma: no cover
    fcntl = None


CONFIG_FILENAME = "tool-hub.json"
STATE_DIR = Path(
    os.environ.get("AGENT_TOOL_HUB_STATE_DIR")
    or os.environ.get("AGENT_TOOL_DOCK_STATE_DIR")
    or Path.home() / ".agent-tool-hub"
)
HUB_PATH_POINTER = STATE_DIR / ".hub-path"


def get_default_hub_path():
    return str(Path.home() / "tool-hub")


def get_saved_hub_path():
    if HUB_PATH_POINTER.exists():
        return HUB_PATH_POINTER.read_text(encoding="utf-8").strip()
    return None


def _write_text_atomically(path, content):
    fd, tmp_path = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=str(path.parent))
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fp:
            fp.write(content)
            fp.flush()
            os.fsync(fp.fileno())
        os.replace(tmp_path, path)
    finally:
        if os.path.exists(tmp_path):
            os.unlink(tmp_path)


def save_hub_path_pointer(hub_path):
    HUB_PATH_POINTER.parent.mkdir(parents=True, exist_ok=True)
    _write_text_atomically(HUB_PATH_POINTER, hub_path)


def load_config(hub_path=None):
    if not hub_path:
        hub_path = get_saved_hub_path() or get_default_hub_path()
    config_path = Path(hub_path) / CONFIG_FILENAME
    if not config_path.exists():
        return None
    with open(config_path, "r", encoding="utf-8") as fp:
        return json.load(fp)


class _ConfigLock:
    def __init__(self, lock_path):
        self.lock_path = lock_path
        self.handle = None

    def __enter__(self):
        self.lock_path.parent.mkdir(parents=True, exist_ok=True)
        self.handle = open(self.lock_path, "a+", encoding="utf-8")
        if fcntl is not None:
            fcntl.flock(self.handle.fileno(), fcntl.LOCK_EX)
        return self.handle

    def __exit__(self, exc_type, exc, tb):
        if self.handle is None:
            return
        if fcntl is not None:
            fcntl.flock(self.handle.fileno(), fcntl.LOCK_UN)
        self.handle.close()
        self.handle = None


def _write_json_atomically(config_path, config):
    fd, tmp_path = tempfile.mkstemp(prefix=f".{config_path.name}.", suffix=".tmp", dir=str(config_path.parent))
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fp:
            json.dump(config, fp, ensure_ascii=False, indent=2)
            fp.flush()
            os.fsync(fp.fileno())
        with open(tmp_path, "r", encoding="utf-8") as fp:
            json.load(fp)
        os.replace(tmp_path, config_path)
    finally:
        if os.path.exists(tmp_path):
            os.unlink(tmp_path)


def save_config(config):
    hub_path = config.get("hub_path", get_default_hub_path())
    Path(hub_path).mkdir(parents=True, exist_ok=True)
    config_path = Path(hub_path) / CONFIG_FILENAME
    lock_path = config_path.with_suffix(config_path.suffix + ".lock")
    with _ConfigLock(lock_path):
        if config_path.exists():
            make_backup(config_path)
        _write_json_atomically(config_path, config)
        save_hub_path_pointer(hub_path)
