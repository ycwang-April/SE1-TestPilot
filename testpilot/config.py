"""Validated centralized settings. Secrets are deliberately absent."""

from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field, ValidationError

from testpilot.errors import ConfigurationError


class SettingsModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class LLMConfig(SettingsModel):
    provider: Literal["deepseek"] = "deepseek"
    model: str = Field(default="deepseek-flash", min_length=1)
    max_retries: int = Field(default=2, ge=0, le=5)
    timeout_seconds: float = Field(default=60, gt=0, le=600)
    # DeepSeek Chat Completions: https://api-docs.deepseek.com/api/create-chat-completion/
    # Verified 2026-10-05. Keep the application's minimum practical JSON budget.
    max_tokens: int = Field(default=16384, ge=512, le=393216)


class ExecutionConfig(SettingsModel):
    preferred_runner: Literal["docker", "local"] = "docker"
    allow_local_fallback: bool = True
    timeout_seconds: float = Field(default=30, gt=0, le=600)
    install_dependencies: bool = False
    install_timeout_seconds: float = Field(default=180, gt=0, le=900)
    docker_image: str = "testpilot-runner:latest"


class AgentConfig(SettingsModel):
    max_repair_rounds: int = Field(default=2, ge=0, le=10)
    context_max_chars: int = Field(default=60000, ge=2000, le=200000)


class CoverageConfig(SettingsModel):
    enabled: bool = True
    line_threshold: float = Field(default=80, ge=0, le=100)
    branch_threshold: float = Field(default=70, ge=0, le=100)
    max_improvement_rounds: int = Field(default=2, ge=0, le=10)


class AppConfig(SettingsModel):
    llm: LLMConfig = Field(default_factory=LLMConfig)
    execution: ExecutionConfig = Field(default_factory=ExecutionConfig)
    agent: AgentConfig = Field(default_factory=AgentConfig)
    coverage: CoverageConfig = Field(default_factory=CoverageConfig)


def load_config(path: str | Path | None = None) -> AppConfig:
    return load_config_with_source(path)[0]


def load_config_with_source(path: str | Path | None = None) -> tuple[AppConfig, Path | None]:
    """Use an explicit file, then cwd/config.yaml, then built-in defaults only if absent."""
    source = path if path is not None else "cwd/config.yaml"
    try:
        source = Path(path).absolute() if path is not None else Path.cwd() / "config.yaml"
        if path is None:
            try:
                source.lstat()
            except FileNotFoundError:
                return AppConfig(), None
        raw = yaml.safe_load(source.read_text(encoding="utf-8"))
        if raw is None:
            raw = {}
        return AppConfig.model_validate(raw), source
    except ValidationError as exc:
        # Do not stringify ValidationError: that includes user-supplied values,
        # potentially including credentials in mistakenly added config fields.
        details = "; ".join(
            f"{'.'.join(str(part) for part in error['loc']) or 'config'}: {error['msg']}"
            for error in exc.errors(include_input=False, include_context=False, include_url=False)
        )
        raise ConfigurationError(f"配置校验失败 ({source}): {details}") from exc
    except (OSError, UnicodeError, yaml.YAMLError) as exc:
        raise ConfigurationError(f"配置读取失败 ({source}): {type(exc).__name__}") from exc
