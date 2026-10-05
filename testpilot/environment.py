"""Load the provider key from the launch directory without importing project settings."""

import os
from pathlib import Path

from dotenv import dotenv_values

from testpilot.errors import ConfigurationError


def load_api_environment(path: Path | None = None) -> None:
    """Prefer an existing environment key; otherwise read only this key from .env."""
    if os.getenv("DEEPSEEK_API_KEY") or os.getenv("TESTPILOT_LOAD_DOTENV") == "0":
        return
    env_file = path if path is not None else Path.cwd() / ".env"
    if not env_file.is_file():
        return
    try:
        # Do not expand variables or load unrelated settings (e.g. tracing or PATH).
        values = dotenv_values(env_file, encoding="utf-8-sig", interpolate=False)
    except (OSError, UnicodeError) as exc:
        raise ConfigurationError("无法读取启动目录中的 .env，请检查文件权限和 UTF-8 编码") from exc
    key = values.get("DEEPSEEK_API_KEY")
    if key and key.strip():
        os.environ["DEEPSEEK_API_KEY"] = key.strip()
