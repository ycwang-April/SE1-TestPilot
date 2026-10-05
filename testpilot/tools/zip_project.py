"""Upload validation shared by ZIP and browser directory projects."""

import io
import stat
import zipfile
from pathlib import Path, PurePosixPath

from testpilot.errors import ProjectAnalysisError

MAX_PROJECT_BYTES = 50_000_000
MAX_PROJECT_FILES = 5000


def _validate_paths(entries: list[tuple[str, bool, bool]], destination: Path) -> None:
    """Validate all paths and collisions before writing any upload content."""
    seen = {}
    spelling = {}
    devices = {"CON", "PRN", "AUX", "NUL"} | {
        f"{x}{i}" for x in ("COM", "LPT") for i in range(1, 10)
    }
    for name, is_dir, is_link in entries:
        path = PurePosixPath(name)
        parts = path.parts
        if (
            not parts
            or path.is_absolute()
            or any(v in ("", ".", "..") for v in name.rstrip("/").split("/"))
            or "\\" in name
            or ":" in name
            or any(ord(c) < 32 for c in name)
            or is_link
            or any(v.rstrip(" .") != v or v.split(".")[0].upper() in devices for v in parts)
            or not (destination / path).resolve().is_relative_to(destination.resolve())
            or any(
                (destination.joinpath(*parts[:i])).is_symlink() for i in range(1, len(parts) + 1)
            )
        ):
            raise ProjectAnalysisError("路径不安全：上传包含不安全路径或符号链接")
        canonical = str(path).casefold()
        if canonical in seen:
            raise ProjectAnalysisError("路径不安全：上传包含重复路径")
        seen[canonical] = is_dir
        for i in range(1, len(parts) + 1):
            prefix = "/".join(parts[:i])
            key = prefix.casefold()
            if key in spelling and spelling[key] != prefix:
                raise ProjectAnalysisError("路径不安全：上传包含重复路径（大小写冲突）")
            spelling[key] = prefix
    for name in seen:
        parents = PurePosixPath(name).parents
        if any(str(parent) in seen and not seen[str(parent)] for parent in parents):
            raise ProjectAnalysisError("路径不安全：文件与目录路径冲突")


def _project_root(destination: Path) -> Path:
    children = list(destination.iterdir())
    return children[0] if len(children) == 1 and children[0].is_dir() else destination


def extract_project(data: bytes, destination: Path) -> Path:
    """Validate the entire archive before extraction, including Windows path hazards."""
    if len(data) > MAX_PROJECT_BYTES:
        raise ProjectAnalysisError("上传文件过大：ZIP 压缩文件须 ≤ 50 MB")
    try:
        with zipfile.ZipFile(io.BytesIO(data)) as archive:
            entries = archive.infolist()
            if len(entries) > MAX_PROJECT_FILES:
                raise ProjectAnalysisError("文件数量过多：ZIP 超过 5000 条目限额")
            if sum(i.file_size for i in entries) > MAX_PROJECT_BYTES:
                raise ProjectAnalysisError("解压后项目过大：总大小须 ≤ 50 MB")
            _validate_paths(
                [
                    (i.orig_filename, i.is_dir(), stat.S_ISLNK(i.external_attr >> 16))
                    for i in entries
                ],
                destination,
            )
            archive.extractall(destination)
    except (zipfile.BadZipFile, OSError, RuntimeError, ValueError) as exc:
        raise ProjectAnalysisError(f"ZIP 损坏或无法解压: {type(exc).__name__}") from exc
    return _project_root(destination)


def extract_directory(files: list[tuple[str, bytes]], destination: Path) -> Path:
    """Restore browser relative filenames as regular files in a temporary workspace."""
    if not files:
        raise ProjectAnalysisError("请选择包含文件的项目目录")
    if len(files) > MAX_PROJECT_FILES:
        raise ProjectAnalysisError("文件数量过多：目录超过 5000 文件限额")
    if sum(len(data) for _, data in files) > MAX_PROJECT_BYTES:
        raise ProjectAnalysisError("上传文件过大：目录文件总大小须 ≤ 50 MB")
    _validate_paths([(name, False, False) for name, _ in files], destination)
    for name, data in files:
        path = destination / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
    return _project_root(destination)
