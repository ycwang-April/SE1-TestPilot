from pydantic import BaseModel, Field


class FunctionInfo(BaseModel):
    name: str
    signature: str
    parameters: list[str] = Field(default_factory=list)
    decorators: list[str] = Field(default_factory=list)
    docstring: str | None = None
    lineno: int
    branches: list[int] = Field(default_factory=list)
    is_async: bool = False


class ClassInfo(BaseModel):
    name: str
    bases: list[str] = Field(default_factory=list)
    decorators: list[str] = Field(default_factory=list)
    docstring: str | None = None
    methods: list[FunctionInfo] = Field(default_factory=list)


class ImportInfo(BaseModel):
    module: str
    names: list[str] = Field(default_factory=list)
    level: int = 0


class ModuleInfo(BaseModel):
    path: str
    module: str
    docstring: str | None = None
    functions: list[FunctionInfo] = Field(default_factory=list)
    classes: list[ClassInfo] = Field(default_factory=list)
    imports: list[ImportInfo] = Field(default_factory=list)
    internal_dependencies: list[str] = Field(default_factory=list)
    branches: list[int] = Field(default_factory=list)


class RepositoryInfo(BaseModel):
    project_path: str
    project_structure: list[str] = Field(default_factory=list)
    source_files: list[str] = Field(default_factory=list)
    existing_tests: list[str] = Field(default_factory=list)
    dependency_info: dict[str, list[str]] = Field(default_factory=dict)
