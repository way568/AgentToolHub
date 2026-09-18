import re
import shutil
from datetime import datetime, timezone
from pathlib import Path


VALID_SLUG_RE = re.compile(r"^[\w.-]+$")


def validate_slug(value, label="标识", error_cls=ValueError):
    text = str(value or "").strip()
    if not text:
        raise error_cls(f"{label}不能为空")
    if ".." in text or "/" in text or "\\" in text:
        raise error_cls(f"{label}不合法: {value}")
    if not VALID_SLUG_RE.fullmatch(text):
        raise error_cls(f"{label}不合法: {value}")
    return text


def resolve_child_path(root, child_name, label="路径", error_cls=ValueError):
    safe_name = validate_slug(child_name, label=label, error_cls=error_cls)
    root_path = Path(root).expanduser().resolve()
    child_path = (root_path / safe_name).resolve()
    try:
        child_path.relative_to(root_path)
    except ValueError as error:
        raise error_cls(f"{label}越界: {child_name}") from error
    return child_path


def make_backup(path):
    source = Path(path)
    if not source.exists():
        return None
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S%f")
    backup_path = source.with_name(f"{source.name}.bak-{timestamp}")
    shutil.copy2(source, backup_path)
    return backup_path


def allow_cors_origin(origin, host, port):
    if not origin:
        return None
    allowed = {
        f"http://{host}:{port}",
        f"http://localhost:{port}",
        f"http://127.0.0.1:{port}",
    }
    return origin if origin in allowed else None

