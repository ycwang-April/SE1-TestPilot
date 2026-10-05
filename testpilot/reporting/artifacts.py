import json
import os
from pathlib import Path

from testpilot.agent.state import AgentState
from testpilot.tools.test_validator import count_test_functions


def redact(text: str) -> str:
    for name, value in os.environ.items():
        if (
            any(part in name.upper() for part in ("KEY", "TOKEN", "SECRET", "PASSWORD"))
            and len(value) >= 8
        ):
            text = text.replace(value, "[REDACTED]")
    return text


class ArtifactWriter:
    def __init__(self, directory: Path):
        self.directory = directory
        directory.mkdir(parents=True, exist_ok=True)

    def json(self, relative: str, data) -> None:
        path = self.directory / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(redact(json.dumps(data, ensure_ascii=False, indent=2)), encoding="utf-8")

    def snapshot(self, state: AgentState) -> None:
        self.json("test_plan.json", [p.model_dump() for p in state.test_plan])
        self.json("trace.json", [event.model_dump() for event in state.history])
        for test in state.generated_tests:
            path = self.directory / "generated_tests" / test.path
            path.parent.mkdir(exist_ok=True)
            path.write_text(redact(test.content), encoding="utf-8")
        if state.execution_result:
            payload = state.execution_result.model_dump(exclude={"coverage_data"})
            self.json("execution_result.json", payload)
            round_path = f"rounds/{len(state.execution_history):02d}"
            self.json(f"{round_path}/execution_result.json", payload)
            self.json(
                f"{round_path}/generated_tests.json",
                [t.model_dump() for t in state.generated_tests],
            )
            self.json(
                f"{round_path}/coverage_result.json",
                state.coverage.model_dump() if state.coverage else None,
            )
        self.json("coverage_result.json", state.coverage.model_dump() if state.coverage else None)

    def finish(self, state: AgentState) -> dict:
        self.snapshot(state)
        first = state.execution_history[0] if state.execution_history else None
        last = state.execution_result
        generated_count = sum(count_test_functions(t.content) for t in state.generated_tests)
        report = {
            "project": Path(state.project_path).name,
            "status": state.status.value,
            "demo": state.demo,
            "modules": len(state.project_index),
            "functions": sum(
                len(m.functions) + sum(len(c.methods) for c in m.classes)
                for m in state.project_index.values()
            ),
            "classes": sum(len(m.classes) for m in state.project_index.values()),
            "targets": state.target_modules,
            "generated_tests": generated_count,  # Compatibility alias, not collected cases.
            "generated_test_functions": generated_count,
            "collected_test_cases": last.collected_test_cases if last else None,
            "passed": last.passed if last else None,
            "failed": last.failed if last else None,
            "errors": last.errors if last else None,
            "skipped": last.skipped if last else None,
            "initial_passed": first.passed if first else None,
            "initial_failed": first.failed if first else None,
            "initial_errors": first.errors if first else None,
            "final_passed": last.passed if last else None,
            "final_failed": last.failed if last else None,
            "final_errors": last.errors if last else None,
            "repair_rounds": state.repair_count,
            "coverage_rounds": state.coverage_round,
            "coverage": state.coverage.model_dump() if state.coverage else None,
            "execution_backend": last.backend if last else "not executed",
            "error": state.error,
            "failure_stage": state.failure_stage,
            "warnings": list(dict.fromkeys(state.warnings)),
            "generated_test_paths": ["generated_tests/" + t.path for t in state.generated_tests],
            "limitations": [
                "高覆盖率不等于高测试质量；断言仍需人工复核",
                "LocalRunner 不提供宿主隔离",
                "只运行新生成的测试；已有测试被识别但不合并执行",
                "上下文和复制大小有限制，超限应使用 --target",
            ],
        }
        self.json("final_report.json", report)
        self.json(
            "state.json",
            state.model_dump(
                mode="json",
                exclude={
                    "selected_context",
                    "generated_tests",
                    "execution_history",
                    "execution_result",
                },
            ),
        )
        if not (self.directory / "execution_result.json").exists():
            self.json("execution_result.json", None)
        lines = [
            "# TestPilot Run Report",
            "",
            f"- Project: {report['project']}",
            f"- Status: {report['status']}",
            f"- Mode: {'DEMO MODE — no real LLM API call' if state.demo else 'DeepSeek'}",
            f"- Modules / functions / classes: {report['modules']} / {report['functions']} / {report['classes']}",
            f"- Generated test functions: {generated_count}",
            f"- Collected pytest cases: {report['collected_test_cases']}",
            f"- Passed / failed / errors / skipped: {report['passed']} / {report['failed']} / {report['errors']} / {report['skipped']}",
            f"- Initial passed / failed / errors: {report['initial_passed']} / {report['initial_failed']} / {report['initial_errors']}",
            f"- Final passed / failed / errors: {report['final_passed']} / {report['final_failed']} / {report['final_errors']}",
            f"- Repair rounds: {state.repair_count}",
            f"- Coverage improvement rounds: {state.coverage_round}",
            f"- Execution Backend: {report['execution_backend'].title()}",
        ]
        lines += [
            "- Counts: generated_test_functions counts definitions; collected_test_cases counts pytest items after parametrization. generated_tests is a compatibility alias for function count. Errors include collection/setup/teardown errors; counts need not sum to collected items. Unavailable collection counts are null."
        ]
        if state.coverage:
            lines += [
                f"- Line coverage: {state.coverage.line_coverage:.2f}%",
                f"- Branch coverage: {state.coverage.branch_coverage:.2f}%",
            ]
        if state.error:
            lines += [f"- Failure stage: {state.failure_stage}", f"- Error: {state.error}"]
        lines += ["", "## Warnings and limitations", ""] + [
            "- " + x for x in report["warnings"] + report["limitations"]
        ]
        lines += ["", "## Generated tests", ""] + [
            f"- [{p}]({p})" for p in report["generated_test_paths"]
        ]
        (self.directory / "final_report.md").write_text(
            redact("\n".join(lines) + "\n"), encoding="utf-8"
        )
        return report
