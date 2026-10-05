from pathlib import PurePosixPath
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator


class TestCasePlan(BaseModel):
    model_config = ConfigDict(extra="forbid")
    category: Literal["normal", "boundary", "exception", "invalid", "branch", "interaction"]
    description: str = Field(min_length=1)
    target_symbol: str = Field(min_length=1)
    input_strategy: str = Field(min_length=1)
    expected_behavior: str = Field(min_length=1)
    priority: int = Field(default=1, ge=1, le=3)
    behavior_id: str = ""
    setup: str = ""
    additional_categories: list[
        Literal["normal", "boundary", "exception", "invalid", "branch", "interaction"]
    ] = Field(default_factory=list)


class TestPlan(BaseModel):
    model_config = ConfigDict(extra="forbid")
    target: str
    cases: list[TestCasePlan] = Field(min_length=1)


class GeneratedTest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    path: str
    content: str = Field(min_length=1, max_length=100000)

    @field_validator("path")
    @classmethod
    def safe_test_path(cls, value: str) -> str:
        p = PurePosixPath(value)
        if (
            "\\" in value
            or ":" in value
            or p.is_absolute()
            or ".." in p.parts
            or len(p.parts) != 1
            or not p.name.startswith("test_")
            or p.suffix != ".py"
            or value != p.name
        ):
            raise ValueError("测试文件必须是 test_*.py basename，禁止目录或路径穿越")
        return value


class TestBundle(BaseModel):
    model_config = ConfigDict(extra="forbid")
    files: list[GeneratedTest] = Field(min_length=1, max_length=50)

    @field_validator("files")
    @classmethod
    def unique_paths(cls, files: list[GeneratedTest]) -> list[GeneratedTest]:
        names = [f.path.casefold() for f in files]
        if len(set(names)) != len(names):
            raise ValueError("重复测试文件名")
        return files
