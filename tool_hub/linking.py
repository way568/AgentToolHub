import os
import stat
import subprocess
from pathlib import Path


class LinkError(RuntimeError):
    """Raised when a managed directory link cannot be created or removed safely."""


_WINDOWS_JUNCTION_TAG = getattr(stat, "IO_REPARSE_TAG_MOUNT_POINT", 0xA0000003)


def _is_windows():
    return os.name == "nt"


def _is_junction(path: Path) -> bool:
    if not _is_windows():
        return False

    is_junction = getattr(path, "is_junction", None)
    if callable(is_junction):
        try:
            if is_junction():
                return True
        except OSError:
            pass

    try:
        st = os.lstat(path)
    except OSError:
        return False
    return getattr(st, "st_reparse_tag", None) == _WINDOWS_JUNCTION_TAG


def create_link(source: Path, target: Path) -> None:
    """Create a managed directory link from target to source."""
    source = Path(source)
    target = Path(target)
    if not source.is_dir():
        raise LinkError(f"link source is not a directory: {source}")
    if link_exists(target):
        raise LinkError(f"link target already exists: {target}")
    target.parent.mkdir(parents=True, exist_ok=True)

    if _is_windows():
        completed = subprocess.run(
            ["cmd", "/c", "mklink", "/J", str(target), str(source)],
            check=False,
            capture_output=True,
            text=True,
        )
        if completed.returncode != 0:
            message = (completed.stderr or completed.stdout or "mklink /J failed").strip()
            raise LinkError(message)
        return

    os.symlink(str(source), str(target), target_is_directory=True)


def remove_link(path: Path) -> None:
    """Remove a managed link only. Never remove a real directory here."""
    path = Path(path)
    if path.is_symlink():
        if _is_windows() and path.is_dir():
            os.rmdir(path)
            return
        path.unlink()
        return
    if _is_junction(path):
        os.rmdir(path)
        return
    raise LinkError(f"refuse to remove non-link directory: {path}")


def is_managed_link(path: Path) -> bool:
    """Return whether path is a symlink / junction used for managed Skill linking."""
    path = Path(path)
    return path.is_symlink() or _is_junction(path)


def resolve_link(path: Path) -> Path:
    """Resolve a symlink / junction target."""
    path = Path(path)
    if not is_managed_link(path):
        raise LinkError(f"path is not a managed link: {path}")
    return Path(os.path.realpath(path))


def link_exists(path: Path) -> bool:
    """Return whether the link path exists or is a broken managed link."""
    path = Path(path)
    return path.exists() or os.path.lexists(str(path)) or is_managed_link(path)


def resolve_link_or_self(path: Path) -> Path:
    """Resolve managed links while leaving real directories untouched."""
    path = Path(path)
    return resolve_link(path) if is_managed_link(path) else path


def link_points_to(path: Path, target: Path) -> bool:
    """Return whether a managed link resolves to target."""
    if not is_managed_link(path):
        return False
    try:
        return resolve_link(path).resolve() == Path(target).resolve()
    except OSError:
        return os.path.normcase(str(resolve_link(path))) == os.path.normcase(str(Path(target)))
