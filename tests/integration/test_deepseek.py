"""Paid integration is opt-in, including when a developer has a key in their shell."""

import os

import pytest

from testpilot.agent.state import Status
from testpilot.service import run_project

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(
        not os.getenv("DEEPSEEK_API_KEY") or os.getenv("TESTPILOT_RUN_INTEGRATION") != "1",
        reason="Requires DEEPSEEK_API_KEY and TESTPILOT_RUN_INTEGRATION=1 (paid API)",
    ),
]


def test_real_deepseek_end_to_end(example_root, local_config, tmp_path):
    state = run_project(example_root / "basic", config=local_config, output=tmp_path / "runs")
    assert state.status == Status.COMPLETED, f"{state.error}; report: {state.run_dir}"
    assert state.execution_result.passed > 0
    assert state.coverage.line_coverage >= local_config.coverage.line_threshold
