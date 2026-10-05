import tokenize
from pathlib import Path

from testpilot.errors import ProjectAnalysisError


class FileReader:
    def read(self, root: Path, relative: str, max_bytes: int = 512_000) -> str:
        path = root / relative
        if path.is_symlink() or not path.resolve().is_relative_to(root.resolve()):
            raise ProjectAnalysisError(f"拒绝越界文件: {relative}")
        try:
            if path.stat().st_size > max_bytes:
                raise ProjectAnalysisError(f"文件过大 (>{max_bytes} bytes): {relative}")
            if path.suffix == ".py":
                with tokenize.open(path) as handle:
                    return handle.read()
            return path.read_text(encoding="utf-8-sig")
        except (OSError, UnicodeError, SyntaxError) as exc:
            raise ProjectAnalysisError(f"无法读取 {relative}: {type(exc).__name__}") from exc
