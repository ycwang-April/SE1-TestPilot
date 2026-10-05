"""Small, exact edits for real-model repair; the agent still receives a TestBundle."""

from pydantic import BaseModel, ConfigDict, Field

from testpilot.errors import LLMOutputValidationError
from testpilot.schemas.test_plan import GeneratedTest, TestBundle
from testpilot.tools.test_validator import retain_tests, validate_tests


class TestEdit(BaseModel):
    model_config = ConfigDict(extra="forbid")
    old: str = Field(min_length=1, description="Exact unique substring of the original file")
    new: str = Field(description="Replacement for that substring only")


class TestPatch(BaseModel):
    model_config = ConfigDict(extra="forbid")
    path: str
    edits: list[TestEdit] = Field(min_length=1)


def apply_patch(original: GeneratedTest, patch: TestPatch) -> TestBundle:
    """Resolve all edits against the original, reject ambiguity and overlap, then commit."""
    if patch.path != original.path:
        raise LLMOutputValidationError(f"本次仅允许修复 {original.path}")
    spans = []
    for edit in patch.edits:
        if original.content.count(edit.old) != 1:
            raise LLMOutputValidationError(
                "修复片段 old 必须在原文件中精确出现一次；请补充相邻行以消除歧义"
            )
        start = original.content.index(edit.old)
        spans.append((start, start + len(edit.old), edit.new))
    spans.sort()
    if any(left[1] > right[0] for left, right in zip(spans, spans[1:])):
        raise LLMOutputValidationError("修复片段不可重叠；请合并相交片段")
    content = original.content
    for start, end, replacement in reversed(spans):
        content = content[:start] + replacement + content[end:]
    tests = [GeneratedTest(path=original.path, content=content)]
    validate_tests(tests)
    retain_tests([original], tests)
    return TestBundle(files=tests)
