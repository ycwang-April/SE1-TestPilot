from importlib import metadata

from packaging.requirements import InvalidRequirement, Requirement

from testpilot.errors import DependencyError
from testpilot.schemas.project import RepositoryInfo


def requirements(repo: RepositoryInfo) -> list[Requirement]:
    parsed = []
    for entries in repo.dependency_info.values():
        for entry in entries:
            try:
                req = Requirement(entry.split(" #", 1)[0])
            except InvalidRequirement as exc:
                raise DependencyError(
                    f"无法安全解析依赖 {entry!r}；仅支持 PEP 508 条目，不支持 pip 指令/-r"
                ) from exc
            if req.url:
                raise DependencyError("不自动安装 URL/VCS/本地路径依赖；请预构建专用 Docker image")
            parsed.append(req)
    return parsed


def check_local_dependencies(repo: RepositoryInfo) -> None:
    missing = []
    for req in requirements(repo):
        if req.marker and not req.marker.evaluate():
            continue
        try:
            version = metadata.version(req.name)
            if req.specifier and version not in req.specifier:
                missing.append(str(req))
        except metadata.PackageNotFoundError:
            missing.append(str(req))
    if missing:
        raise DependencyError(
            "缺失或版本不匹配的依赖: "
            + ", ".join(missing)
            + "；请在独立环境准备依赖，或明确启用 Docker 依赖安装"
        )
