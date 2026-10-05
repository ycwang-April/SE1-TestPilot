"""Small presentation helpers; all result data comes from saved run artifacts."""

import io
import json
import re
import zipfile
from pathlib import Path

import streamlit as st

from testpilot.reporting.artifacts import redact
from testpilot.reporting.runs import project_slug, run_time_and_id


def read_json(directory: Path, name: str):
    return json.loads((directory / name).read_text(encoding="utf-8"))


def generated_files(directory: Path) -> list[Path]:
    root = directory / "generated_tests"
    if root.is_symlink():
        return []
    return sorted(p for p in root.glob("test_*.py") if p.is_file() and not p.is_symlink())


def downloads(directory: Path) -> list[tuple[str, str, str, bytes]]:
    """Download exact stored bytes; never include project sources or credential files."""
    project = project_slug(read_json(directory, "final_report.json")["project"])
    result = []
    for label, name, suffix, mime in [
        ("Download Final Report (.md)", "final_report.md", "final-report.md", "text/markdown"),
        ("Download test_plan.json", "test_plan.json", "test-plan.json", "application/json"),
        ("Download trace.json", "trace.json", "trace.json", "application/json"),
    ]:
        path = directory / name
        if path.is_file() and not path.is_symlink():
            result.append((label, f"{project}-{suffix}", mime, path.read_bytes()))
    files = generated_files(directory)
    if files:
        buffer = io.BytesIO()
        with zipfile.ZipFile(buffer, "w", compression=zipfile.ZIP_DEFLATED) as archive:
            for path in files:
                archive.writestr(f"generated_tests/{path.name}", path.read_bytes())
        result.insert(
            1,
            (
                "Download Generated Tests (.zip)",
                f"{project}-generated-tests.zip",
                "application/zip",
                buffer.getvalue(),
            ),
        )
    return result


def failure_details(error: str, stage: str, execution: dict | None = None) -> tuple[str, str]:
    match = re.search(r"\b([A-Za-z]+Error)\b", error)
    if match:
        kind = match.group(1)
    elif execution and execution.get("timed_out"):
        kind = "TestExecutionError (timeout)"
    else:
        kind = {"REPAIR": "TestExecutionError", "IMPROVE_COVERAGE": "CoverageError"}.get(
            stage, "WorkflowError"
        )
    if "DEEPSEEK_API_KEY" in error:
        suggestion = "请在启动目录 .env 或终端环境配置 DEEPSEEK_API_KEY，再重试。"
    elif kind == "ConfigurationError":
        suggestion = "请按错误中指出的字段、类型或范围修改 config.yaml，保存后重新运行页面。"
    elif "OutputTruncated" in kind or "LengthFinishReason" in kind:
        suggestion = (
            "模型输出达到长度上限；请查看 llm_calls.json，缩小目标或调整 llm.max_tokens 后重试。"
        )
    elif "预算" in error or "context_max_chars" in error:
        suggestion = "请指定目标模块缩小范围，或调整 config.yaml 的 agent.context_max_chars。"
    elif "Docker" in error:
        suggestion = "请启动 Docker daemon 并构建 runner 镜像；仅对可信项目考虑 Local。"
    elif "OutputValidation" in kind:
        suggestion = "模型输出未通过结构或测试校验；请检查测试计划，缩小目标后重试。"
    elif "timeout" in error.lower() or (execution and execution.get("timed_out")):
        suggestion = "请检查耗时或阻塞调用，并按需调整对应 API / execution timeout。"
    elif "Coverage" in kind or "coverage" in error.lower():
        suggestion = "请检查覆盖率产物、pytest-cov、目标路径及补测预算。"
    else:
        suggestion = "请检查输入与折叠区中的执行证据；修正原因后重新运行。"
    return kind, suggestion


def show_failure(error: str, stage: str, execution: dict | None = None) -> None:
    error = redact(error)
    kind, suggestion = failure_details(error, stage, execution)
    st.error("FAIL / FAILED")
    st.write(f"Failure Stage: {stage or 'unknown'} · Error Type: {kind}")
    st.write(error.splitlines()[0][:350] if error else "运行失败，请查看详细错误信息。")
    st.warning(suggestion)
    with st.expander("详细错误信息", expanded=False):
        st.code(error, language="text")
        if execution and execution.get("traceback"):
            st.code(redact(execution["traceback"]), language="text")


def show_result(directory: Path) -> None:
    try:
        report = read_json(directory, "final_report.json")
        trace = read_json(directory, "trace.json")
        execution = read_json(directory, "execution_result.json")
        st.divider()
        st.subheader("本次运行结果")
        mode = "DEMO MODE — no real LLM API call" if report["demo"] else "REAL LLM — DeepSeek"
        backend = report.get("execution_backend", "not executed")
        backend_label = {"docker": "Docker", "local": "Local"}.get(backend, "Not executed")
        started, short_id = run_time_and_id(directory)
        st.write(f"Project: {redact(report['project'])}")
        st.caption(f"Mode: {mode} · Execution Backend: {backend_label}")
        st.caption(f"Run Time: {started}")
        st.caption(f"Run ID: {short_id}")
        if report["status"] == "COMPLETED":
            st.success("FINISH / COMPLETED")
        else:
            show_failure(report.get("error") or "", report.get("failure_stage") or "", execution)

        st.markdown("**Agent Workflow · 实际执行轨迹**")
        st.code(
            " → ".join(event["action"] for event in trace) or "尚无节点记录",
            language="text",
            wrap_lines=True,
        )
        repairs, improvements = report["repair_rounds"], report["coverage_rounds"]
        if any(event["action"] in ("REPAIR", "IMPROVE_COVERAGE") for event in trace):
            st.info(f"Feedback Loop: REPAIR × {repairs} · IMPROVE_COVERAGE × {improvements}")
        st.caption(f"repair_count: {repairs} · coverage_round: {improvements}")

        cov = report.get("coverage") or {}
        metrics = [
            ("Collected Tests", report.get("collected_test_cases")),
            ("Passed", report.get("passed", report.get("final_passed"))),
            (
                "Failed / Errors",
                f"{_value(report.get('failed', report.get('final_failed')))} / "
                f"{_value(report.get('errors', report.get('final_errors')))}",
            ),
            ("Execution Backend", backend_label),
            ("Line Coverage", _percentage(cov.get("line_coverage"))),
            ("Branch Coverage", _percentage(cov.get("branch_coverage"))),
            ("Repair Rounds", repairs),
            ("Coverage Improvement Rounds", improvements),
        ]
        for start in (0, 4):
            with st.container(horizontal=True):
                for label, value in metrics[start : start + 4]:
                    st.metric(label, _value(value), width=210, help=label)
        functions = report.get("generated_test_functions", report.get("generated_tests"))
        st.caption(
            f"Generated Test Functions: {_value(functions)} · "
            f"Collected Pytest Cases: {_value(report.get('collected_test_cases'))} · "
            "参数化会展开为多个 pytest cases；高覆盖率不等于高测试质量。"
        )
        if backend == "local":
            st.warning("LocalRunner — host isolation disabled")
        elif backend == "docker":
            st.caption("Execution Backend: Docker")
        warnings = list(dict.fromkeys(report.get("warnings", [])))
        for warning in warnings:
            if warning.startswith("Docker fallback:"):
                st.warning(redact(warning)[:500])
        other_warnings = [
            w
            for w in warnings
            if not w.startswith("Docker fallback:") and "host isolation disabled" not in w
        ]
        if other_warnings:
            with st.expander(f"运行提示（{len(other_warnings)}）", expanded=False):
                for warning in other_warnings:
                    st.write(redact(warning)[:500])

        with st.container(horizontal=True):
            for label, filename, mime, data in downloads(directory):
                st.download_button(label, data, file_name=filename, mime=mime, on_click="ignore")
        for label, name in [
            ("最终报告", "final_report.md"),
            ("测试计划", "test_plan.json"),
            ("Agent Trace", "trace.json"),
        ]:
            with st.expander(label, expanded=False):
                content = redact((directory / name).read_text(encoding="utf-8"))
                st.markdown(content) if name.endswith(".md") else st.json(content)
        with st.expander("Generated Tests", expanded=False):
            for path in generated_files(directory):
                st.caption(path.name)
                st.code(redact(path.read_text(encoding="utf-8")), language="python")
    except (OSError, ValueError, KeyError, TypeError) as exc:
        st.error(f"运行产物无法读取（{type(exc).__name__}），请重新运行或检查 run 目录。")


def _value(value) -> str:
    return "—" if value is None else str(value)


def _percentage(value) -> str:
    return "—" if value is None else f"{value:.1f}%"
