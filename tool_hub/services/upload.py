import re
import shutil
import tempfile
import zipfile
from pathlib import Path

from tool_hub.config_store import get_default_hub_path
from tool_hub.errors import ToolHubError
from tool_hub.safety import resolve_child_path, validate_slug


class UploadSkillService:
    def upload(self, config, headers, body):
        if not config:
            raise ToolHubError("未初始化")

        hub_path = Path(config.get("hub_path", get_default_hub_path()))
        content_type = headers.get("Content-Type", "")
        if "multipart/form-data" not in content_type:
            raise ToolHubError("需要 multipart/form-data")

        boundary = self._extract_boundary(content_type)
        if not boundary:
            raise ToolHubError("缺少 boundary")

        filename, file_data = self._extract_file(body, boundary)
        if not file_data or not filename:
            raise ToolHubError("未找到上传文件")
        filename = self._validate_filename(filename)
        if not filename.endswith(".zip"):
            raise ToolHubError("只支持 .zip 文件")

        tmp_dir = Path(tempfile.mkdtemp())
        try:
            zip_path = tmp_dir / filename
            with open(zip_path, "wb") as fp:
                fp.write(file_data)

            with zipfile.ZipFile(zip_path, "r") as zf:
                zf.extractall(tmp_dir)

            skill_root, skill_name = self._resolve_skill_root(tmp_dir, filename)
            frontmatter = self._read_frontmatter(skill_root / "SKILL.md")
            skill_name = validate_slug(frontmatter["name"], label="skill_id", error_cls=ToolHubError)
            target_dir = resolve_child_path(hub_path, skill_name, label="skill_id", error_cls=ToolHubError)
            if target_dir.exists():
                raise ToolHubError(f"已存在同名 skill: {skill_name}")

            if skill_root == tmp_dir:
                target_dir.mkdir(parents=True, exist_ok=True)
                for item in tmp_dir.iterdir():
                    if item.name != filename:
                        shutil.move(str(item), str(target_dir / item.name))
            else:
                hub_path.mkdir(parents=True, exist_ok=True)
                shutil.move(str(skill_root), str(target_dir))

            return {
                "success": True,
                "skill": {
                    "name": skill_name,
                    "description": frontmatter["description"],
                },
            }
        except zipfile.BadZipFile as error:
            raise ToolHubError("zip 文件格式错误") from error
        finally:
            shutil.rmtree(tmp_dir, ignore_errors=True)

    def _extract_boundary(self, content_type):
        for part in content_type.split(";"):
            if "boundary=" in part:
                return part.split("boundary=", 1)[1].strip().strip('"')
        return None

    def _extract_file(self, body, boundary):
        boundary_bytes = boundary.encode("utf-8")
        filename = None
        file_data = None

        for part in body.split(boundary_bytes):
            if not part or part in (b"--", b"--\r\n"):
                continue
            header_end = part.find(b"\r\n\r\n")
            if header_end == -1:
                continue
            raw_headers = part[:header_end].decode("utf-8", errors="ignore")
            payload = part[header_end + 4 :]
            if payload.endswith(b"\r\n"):
                payload = payload[:-2]
            match = re.search(r'filename="([^"]+)"', raw_headers)
            if match:
                filename = match.group(1)
                file_data = payload
                break

        return filename, file_data

    def _validate_filename(self, filename):
        safe_name = str(filename or "").strip()
        if not safe_name:
            raise ToolHubError("上传文件名不能为空")
        if "/" in safe_name or "\\" in safe_name or ".." in safe_name:
            raise ToolHubError(f"上传文件名不合法: {filename}")
        if Path(safe_name).is_absolute():
            raise ToolHubError(f"上传文件名不合法: {filename}")
        return safe_name

    def _resolve_skill_root(self, tmp_dir, filename):
        extracted = [
            item
            for item in tmp_dir.iterdir()
            if item.name not in (filename, "__MACOSX", ".DS_Store")
        ]
        if len(extracted) == 1 and extracted[0].is_dir():
            return extracted[0], extracted[0].name
        return tmp_dir, filename[:-4]

    def _read_frontmatter(self, skill_md_path):
        if not skill_md_path.exists():
            raise ToolHubError("缺少 SKILL.md 文件")

        content = skill_md_path.read_text(encoding="utf-8")
        if not content.startswith("---"):
            raise ToolHubError("SKILL.md 缺少 frontmatter（需要以 --- 开头）")

        parts = content.split("---")
        if len(parts) < 3:
            raise ToolHubError("frontmatter 格式错误（需要 --- 包围）")

        frontmatter = {}
        for line in parts[1].strip().splitlines():
            if ":" not in line:
                continue
            key, value = line.split(":", 1)
            frontmatter[key.strip()] = value.strip().strip('"').strip("'")

        if not frontmatter.get("name"):
            raise ToolHubError("frontmatter 缺少 name 字段")
        if not frontmatter.get("description"):
            raise ToolHubError("frontmatter 缺少 description 字段")
        return frontmatter
