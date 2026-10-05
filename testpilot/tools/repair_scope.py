"""Select repair files from real pytest observations, never from model claims."""

import re

from testpilot.schemas.execution import ExecutionResult
from testpilot.schemas.test_plan import GeneratedTest


def repair_paths(tests: list[GeneratedTest], execution: ExecutionResult | None) -> list[str]:
    if execution is None:
        return [test.path for test in tests]
    output = "\n".join((execution.traceback, execution.stdout, execution.stderr)).replace("\\", "/")
    # Prefer pytest's failure summary to avoid unrelated files mentioned in stack frames.
    summaries = re.findall(r"(?m)^(?:FAILED|ERROR)\s+([^\n]+)", output)
    mentioned = {
        name
        for line in summaries
        for name in re.findall(r"(?:^|/)(test_[^/:\s]+\.py)(?=::|\s|$)", line)
    }
    if not mentioned:
        mentioned = set(re.findall(r"(?:^|/)(test_[^/:\s\"']+\.py)(?=[:\s\"']|$)", output))
    selected = [test.path for test in tests if test.path in mentioned]
    # Timeout/truncated collection output may contain no attributable test filename.
    return selected or [test.path for test in tests]
