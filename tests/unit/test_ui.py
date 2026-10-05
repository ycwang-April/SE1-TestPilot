"""Streamlit AppTest and artifact downloads, without real model calls."""

import importlib
import io
import json
import zipfile
from pathlib import Path

import pytest

from testpilot import service
from testpilot.errors import DockerUnavailableError, ProjectAnalysisError
from testpilot.runners.factory import FallbackRunner

st = pytest.importorskip("streamlit")
AppTest = importlib.import_module("streamlit.testing.v1").AppTest
ui = importlib.import_module("testpilot.ui.streamlit_app")
results = importlib.import_module("testpilot.ui.results")
APP = Path(ui.__file__)


def app():
    return AppTest.from_file(str(APP), default_timeout=40).run()


def text(elements):
    return "\n".join(str(element.value) for element in elements)


@pytest.fixture
def demo_run(example_root, local_config, tmp_path):
    return service.run_project(
        example_root / "edge_cases", config=local_config, demo=True, output=tmp_path / "runs"
    )


def test_load_modes_effective_yaml_and_overrides(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    (tmp_path / "config.yaml").write_text(
        "llm:\n  model: configured-model\nagent:\n  context_max_chars: 80000\n"
        "execution:\n  preferred_runner: local\ncoverage:\n  line_threshold: 83\n"
        "  branch_threshold: 72\n",
        encoding="utf-8",
    )
    page = app()
    assert not page.exception
    assert "DEMO MODE — no real LLM API call" in text(page.info)
    assert "Model: configured-model" in text(page.caption)
    assert "Context Budget: 80000 chars" in text(page.caption)
    assert "Line 83% / Branch 72%" in text(page.caption)
    page.checkbox(key="demo").uncheck()
    page.selectbox(key="runner").select("docker")
    page.slider(key="line").set_value(91.0)
    page.slider(key="branch").set_value(84.0)
    page.run()
    assert "REAL LLM — DeepSeek" in text(page.info)
    assert "Runner: Docker" in text(page.caption)
    assert "Line 91% / Branch 84%" in text(page.caption)
    assert "DEMO MODE" not in text(page.info)


def test_success_metrics_trace_downloads_and_persisted_mode(demo_run, monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    (tmp_path / "config.yaml").write_text("agent:\n  context_max_chars: 80000\n", encoding="utf-8")
    captured = []

    def run(project, **kwargs):
        captured.append((project, kwargs))
        kwargs["observer"](demo_run)
        return demo_run

    monkeypatch.setattr(service, "run_project", run)
    page = app()
    page.selectbox(key="runner").select("local")
    page.button[0].click().run()
    assert not page.exception
    assert captured[0][0] == Path(ui.example_path("edge_cases"))
    assert captured[0][1]["config"].agent.context_max_chars == 80000
    metrics = {m.label: m.value for m in page.metric}
    assert metrics == {
        "Collected Tests": "9",
        "Passed": "9",
        "Failed / Errors": "0 / 0",
        "Execution Backend": "Local",
        "Line Coverage": "100.0%",
        "Branch Coverage": "100.0%",
        "Repair Rounds": "1",
        "Coverage Improvement Rounds": "1",
    }
    trace = json.loads((Path(demo_run.run_dir) / "trace.json").read_text())
    assert " → ".join(e["action"] for e in trace) in text(page.code)
    assert "REPAIR × 1 · IMPROVE_COVERAGE × 1" in text(page.info)
    assert "Generated Test Functions: 3 · Collected Pytest Cases: 9" in text(page.caption)
    assert "FINISH / COMPLETED" in text(page.success)
    assert "LocalRunner — host isolation disabled" in text(page.warning)
    assert "# TestPilot Run Report" in text(page.markdown)
    assert all(not e.proto.expanded for e in page.expander)
    assert len(page.get("download_button")) == 4
    page.checkbox(key="demo").uncheck().run()
    assert "REAL LLM — DeepSeek" in text(page.info)
    assert "Mode: DEMO MODE — no real LLM API call · Execution Backend: Local" in text(page.caption)
    assert "Project: edge_cases" in text(page.markdown)
    assert "Run Time:" in text(page.caption) and "UTC+08:00" in text(page.caption)
    assert "Run ID: " + Path(demo_run.run_dir).name.rsplit("-", 1)[1] in text(page.caption)
    assert len(captured) == 1  # Changing controls never reruns the workflow.


def test_download_bytes_and_zip_allowlist(demo_run):
    root = Path(demo_run.run_dir)
    (root / ".env").write_text("SECRET=do-not-export")
    (root / "generated_tests/.env").write_text("SECRET=do-not-export")
    (root / "generated_tests/helper.txt").write_text("not a generated test")
    payloads = results.downloads(root)
    assert len(payloads) == 4
    for label, filename, mime, data in payloads:
        expected_names = {
            "Download Final Report (.md)": "edge_cases-final-report.md",
            "Download Generated Tests (.zip)": "edge_cases-generated-tests.zip",
            "Download test_plan.json": "edge_cases-test-plan.json",
            "Download trace.json": "edge_cases-trace.json",
        }
        assert filename == expected_names[label]
        if mime == "application/zip":
            with zipfile.ZipFile(io.BytesIO(data)) as archive:
                assert archive.namelist() == [
                    "generated_tests/test_shipping.py",
                    "generated_tests/test_shipping_extra.py",
                ]
                for name in archive.namelist():
                    assert archive.read(name) == (root / name).read_bytes()
        else:
            name = {
                "Download Final Report (.md)": "final_report.md",
                "Download test_plan.json": "test_plan.json",
                "Download trace.json": "trace.json",
            }[label]
            assert data == (root / name).read_bytes()
        assert b"do-not-export" not in data


def test_fallback_uses_actual_backend(example_root, tmp_path, monkeypatch):
    original = service.run_project

    def unavailable(self):
        raise DockerUnavailableError("Docker unavailable in UI test")

    monkeypatch.setattr("testpilot.runners.docker_runner.DockerTestRunner.probe", unavailable)

    def run(project, **kwargs):
        kwargs["output"] = tmp_path
        kwargs["runner"] = FallbackRunner(kwargs["config"].execution)
        return original(project, **kwargs)

    monkeypatch.setattr(service, "run_project", run)
    page = app()
    page.selectbox(key="runner").select("docker")
    page.button[0].click().run()
    assert not page.exception
    assert "-demo-local-" in Path(page.session_state["run_dir"]).name
    assert "Docker fallback:" in text(page.warning)
    assert "LocalRunner — host isolation disabled" in text(page.warning)
    assert {m.label: m.value for m in page.metric}["Execution Backend"] == "Local"


@pytest.mark.parametrize("name", ui.EXAMPLES)
def test_examples_and_custom_local_source(name, monkeypatch, tmp_path):
    calls = []

    def capture(project, **kwargs):
        calls.append(project)
        raise ProjectAnalysisError("stop before execution")

    monkeypatch.setattr(service, "run_project", capture)
    page = app()
    page.selectbox(key="example").select(name)
    page.button[0].click().run()
    assert calls == [Path(ui.example_path(name))]
    assert not page.exception
    page.checkbox(key="demo").uncheck()
    page.selectbox(key="example").select("自定义项目").run()
    page.text_input(key="project_path").input(str(tmp_path))
    page.button[0].click().run()
    assert calls[-1] == tmp_path
    assert not page.exception


class Upload(io.BytesIO):
    def __init__(self, name, data):
        super().__init__(data)
        self.name = name


def test_sources_are_exclusive_and_directory_restored(tmp_path):
    upload = Upload("project/src/a.py", b"x=1")
    with pytest.raises(ProjectAnalysisError, match="仅提供一个"):
        ui.select_project("选择项目目录", "other", [upload], None, tmp_path)
    with pytest.raises(ProjectAnalysisError, match="仅提供一个"):
        ui.select_project("上传 ZIP", "", [upload], upload, tmp_path)
    with pytest.raises(ProjectAnalysisError, match="仅提供一个"):
        ui.select_project("上传 ZIP", "", [], None, tmp_path)
    assert not list(tmp_path.iterdir())
    root = ui.select_project("选择项目目录", "", [upload], None, tmp_path)
    assert (root / "src/a.py").read_bytes() == b"x=1"


@pytest.mark.parametrize("source", ["选择项目目录", "上传 ZIP"])
def test_uploader_limits_and_demo_block(source):
    page = app()
    page.radio(key="source").set_value(source).run()
    assert not page.exception
    assert page.button[0].disabled
    assert "上传项目请关闭 Demo" in text(page.warning)
    upload = page.get("file_uploader")[0]
    assert upload.proto.max_upload_size_mb == 50
    assert upload.proto.accept_directory == (source == "选择项目目录")
    page.checkbox(key="demo").uncheck().run()
    assert not page.button[0].disabled
    page.button[0].click().run()
    assert not page.exception
    assert "FAIL / FAILED" in text(page.error)
    page.radio(key="source").set_value("本地路径").run()
    assert not page.get("file_uploader")


def test_missing_key_failure_real_workflow(tmp_path, monkeypatch):
    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)
    original = service.run_project
    monkeypatch.setattr(
        service, "run_project", lambda project, **kw: original(project, output=tmp_path, **kw)
    )
    page = app()
    page.checkbox(key="demo").uncheck()
    page.button[0].click().run()
    assert not page.exception
    assert "FAIL / FAILED" in text(page.error)
    assert "Error Type: ConfigurationError" in text(page.markdown)
    assert "DEEPSEEK_API_KEY" in text(page.warning)
    assert {m.label: m.value for m in page.metric}["Collected Tests"] == "—"
    assert "ANALYZE → PLAN → FAIL" in text(page.code)


@pytest.mark.parametrize(
    "error,stage,expected",
    [
        ("DockerUnavailableError: Docker unavailable", "EXECUTE", "Docker daemon"),
        ("ProjectAnalysisError: 超过预算 context_max_chars", "GENERATE", "目标模块"),
        ("LLMOutputValidationError: invalid output", "PLAN", "结构或测试校验"),
        ("LLMOutputTruncatedError: 输出预算不足 llm.max_tokens", "REPAIR", "长度上限"),
        ("Internal LengthFinishReasonError", "REPAIR", "长度上限"),
        ("TestExecutionError: pytest timeout", "EXECUTE", "timeout"),
        ("CoverageError: coverage missing", "EXECUTE", "pytest-cov"),
    ],
)
def test_failure_artifacts_render_without_traceback_sprawl(
    demo_run, error, stage, expected, monkeypatch
):
    root = Path(demo_run.run_dir)
    report = results.read_json(root, "final_report.json")
    report.update(status="FAILED", error=error, failure_stage=stage)
    (root / "final_report.json").write_text(json.dumps(report))
    page = app()
    page.session_state["run_dir"] = str(root)
    page.run()
    assert not page.exception
    assert "FAIL / FAILED" in text(page.error)
    assert expected in text(page.warning)
    assert any(e.label == "详细错误信息" and not e.proto.expanded for e in page.expander)


def test_invalid_config_and_missing_artifact_are_friendly(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    (tmp_path / "config.yaml").write_text("agent: {context_max_chars: 1}")
    page = app()
    assert not page.exception
    assert "Error Type: ConfigurationError" in text(page.markdown)
    (tmp_path / "config.yaml").unlink()
    page = app()
    page.session_state["run_dir"] = str(tmp_path / "missing")
    page.run()
    assert not page.exception
    assert "运行产物无法读取" in text(page.error)


def test_output_budget_50000_loads_and_invalid_budget_is_actionable(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    config = tmp_path / "config.yaml"
    config.write_text("llm: {max_tokens: 50000}\n", encoding="utf-8")
    page = app()
    assert not page.exception and not page.error
    assert "Max Output: 50000 tokens" in text(page.caption)
    assert page.button[0].label == "分析并生成测试"
    page.checkbox(key="demo").uncheck().run()
    assert not page.exception and not page.error
    assert "REAL LLM — DeepSeek" in text(page.info)
    assert "Max Output: 50000 tokens" in text(page.caption)
    config.write_text("llm: {max_tokens: 393217}\n", encoding="utf-8")
    page.run()
    assert not page.exception
    assert "llm.max_tokens" in text(page.markdown)
    assert "393216" in text(page.markdown)
    assert "config.yaml" in text(page.warning)
