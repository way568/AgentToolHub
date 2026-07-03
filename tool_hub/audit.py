import json
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4


LOG_FILENAME = ".tool-hub-log.jsonl"


def log_path(hub_path):
    return Path(hub_path) / LOG_FILENAME


def append_log(hub_path, batch_id, action, skill_name, detail, reversible=True):
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
    path = log_path(hub_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "a", encoding="utf-8") as fp:
        fp.write(json.dumps(entry, ensure_ascii=False) + "\n")
    return entry


def read_logs(hub_path, batch_id=None):
    path = log_path(hub_path)
    if not path.exists():
        return []
    logs = []
    with open(path, "r", encoding="utf-8") as fp:
        for line in fp:
            line = line.strip()
            if not line:
                continue
            entry = json.loads(line)
            if batch_id and entry.get("batch_id") != batch_id:
                continue
            logs.append(entry)
    return logs


def update_log_entry(hub_path, log_id, updates):
    path = log_path(hub_path)
    if not path.exists():
        return False
    lines = []
    found = False
    with open(path, "r", encoding="utf-8") as fp:
        for line in fp:
            line = line.strip()
            if not line:
                continue
            entry = json.loads(line)
            if entry["id"] == log_id:
                entry.update(updates)
                found = True
            lines.append(json.dumps(entry, ensure_ascii=False))
    if found:
        with open(path, "w", encoding="utf-8") as fp:
            fp.write("\n".join(lines) + "\n")
    return found

