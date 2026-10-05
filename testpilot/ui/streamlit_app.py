"""Run with: streamlit run testpilot/ui/streamlit_app.py"""

import inspect
import tempfile
from pathlib import Path

import streamlit as st
from packaging.version import Version

from testpilot.config import load_config_with_source
from testpilot.errors import ProjectAnalysisError, TestPilotError
from testpilot.reporting.artifacts import redact
from testpilot.service import run_project
from testpilot.tools.zip_project import (
    MAX_PROJECT_BYTES,
    MAX_PROJECT_FILES,
    extract_directory,
    extract_project,
)
from testpilot.ui.results import show_failure, show_result

EXAMPLES = ("basic", "multi_module", "edge_cases", "advanced_project")
EXAMPLE_ROOT = Path(__file__).resolve().parents[2] / "examples"
SOURCES = ("本地路径", "选择项目目录", "上传 ZIP")


def example_path(name: str) -> str:
    if name not in EXAMPLES:
        raise ProjectAnalysisError("未知示例项目")
    return str(EXAMPLE_ROOT / name)


def select_project(source, path, uploaded_files, uploaded_zip, destination: Path) -> Path:
    """Only one explicit source is accepted; no hidden source takes precedence."""
    present = [bool(path and path.strip()), bool(uploaded_files), uploaded_zip is not None]
    if source not in SOURCES or sum(present) != 1 or not present[SOURCES.index(source)]:
        raise ProjectAnalysisError("请选择且仅提供一个项目来源：本地路径、项目目录或 ZIP")
    if source == "本地路径":
        return Path(path.strip())
    if source == "上传 ZIP":
        if uploaded_zip.getbuffer().nbytes > MAX_PROJECT_BYTES:
            raise ProjectAnalysisError("上传文件过大：ZIP 压缩文件须 ≤ 50 MB")
        return extract_project(uploaded_zip.getvalue(), destination)
    if len(uploaded_files) > MAX_PROJECT_FILES:
        raise ProjectAnalysisError("文件数量过多：目录超过 5000 文件限额")
    if sum(file.getbuffer().nbytes for file in uploaded_files) > MAX_PROJECT_BYTES:
        raise ProjectAnalysisError("上传文件过大：目录文件总大小须 ≤ 50 MB")
    return extract_directory([(file.name, file.getvalue()) for file in uploaded_files], destination)


def main() -> None:
    st.set_page_config(page_title="TestPilot", page_icon="🧪", layout="wide")
    st.title("TestPilot")
    st.caption("项目级测试生成 · 真实执行反馈 · 可审查运行证据")
    try:
        config, config_source = load_config_with_source()
    except TestPilotError as exc:
        show_failure(f"{type(exc).__name__}: {exc}", "CONFIGURATION")
        return
    with st.sidebar:
        demo = st.checkbox("Demo Mode（无真实 API 调用）", value=True, key="demo")
        runner = st.selectbox(
            "执行后端",
            ["docker", "local"],
            index=0 if config.execution.preferred_runner == "docker" else 1,
            key="runner",
        )
        target = st.text_input(
            "目标模块（可选，留空则分析全部模块）",
            placeholder="例如：src/order.py；留空则扫描全部模块",
            key="target",
        )
        line = st.slider(
            "行覆盖率目标", 0.0, 100.0, float(config.coverage.line_threshold), step=1.0, key="line"
        )
        branch = st.slider(
            "分支覆盖率目标",
            0.0,
            100.0,
            float(config.coverage.branch_threshold),
            step=1.0,
            key="branch",
        )
        st.caption("Docker 不可用时按配置决定是否回退 Local；Local 仅适用于可信项目。")
    config.execution.preferred_runner = runner
    config.coverage.line_threshold = line
    config.coverage.branch_threshold = branch
    st.info("DEMO MODE — no real LLM API call" if demo else "REAL LLM — DeepSeek")
    st.markdown("**当前有效配置（下次运行）**")
    st.caption(
        f"Mode: {'Demo' if demo else 'Real DeepSeek'} · Model: {redact(config.llm.model)} · "
        f"Runner: {runner.title()} · Context Budget: {config.agent.context_max_chars} chars"
    )
    st.caption(f"Max Output: {config.llm.max_tokens} tokens（单次输出上限）")
    st.caption(
        f"Coverage Target: Line {line:g}% / Branch {branch:g}%"
        if config.coverage.enabled
        else "Coverage Target: Disabled（配置已关闭 coverage）"
    )
    st.caption(f"Config: {config_source.name if config_source else 'built-in defaults'}")

    directory_supported = Version(st.__version__) >= Version("1.49")
    sources = SOURCES if directory_supported else (SOURCES[0], SOURCES[2])
    source = st.radio("项目来源（仅当前选中项生效）", sources, horizontal=True, key="source")
    path, uploaded_files, uploaded_zip = "", [], None
    upload_kwargs = (
        {"max_upload_size": 50}
        if "max_upload_size" in inspect.signature(st.file_uploader).parameters
        else {}
    )
    if source == "本地路径":
        example = st.selectbox(
            "示例项目",
            [*EXAMPLES, "自定义项目"],
            index=2,
            key="example",
        )
        if example == "自定义项目":
            path = st.text_input(
                "本地项目目录", placeholder="例如：examples/advanced_project", key="project_path"
            )
        else:
            path = example_path(example)
            st.caption(f"本地项目目录：examples/{example}")
    elif source == "选择项目目录":
        st.caption(
            "上传目录内容到临时工作区，保留相对路径；总大小 ≤ 50 MB，最多 5000 文件。原目录不变。"
        )
        uploaded_files = st.file_uploader(
            "选择项目目录",
            accept_multiple_files="directory",
            key="directory_upload",
            help="总文件大小 ≤ 50 MB（50,000,000 bytes），最多 5000 文件。",
            **upload_kwargs,
        )
    else:
        st.caption("ZIP ≤ 50 MB，解压后总大小 ≤ 50 MB（50,000,000 bytes），最多 5000 条目。")
        uploaded_zip = st.file_uploader(
            "上传 ZIP 项目",
            type="zip",
            key="zip_upload",
            **upload_kwargs,
        )
    if demo:
        st.caption("Demo 仅支持未修改的内置示例，并校验源码指纹；任意项目请关闭 Demo。")
    blocked_demo = demo and source != "本地路径"
    if blocked_demo:
        st.warning("上传项目请关闭 Demo；离线演示请选择本地内置示例。")
    if st.button("分析并生成测试", type="primary", disabled=blocked_demo):
        st.session_state.pop("run_dir", None)
        st.session_state.pop("run_config", None)
        with tempfile.TemporaryDirectory(prefix="testpilot-upload-") as temp:
            try:
                project = select_project(source, path, uploaded_files, uploaded_zip, Path(temp))
                if demo and project.resolve() not in {
                    Path(example_path(n)).resolve() for n in EXAMPLES
                }:
                    raise ProjectAnalysisError("Demo 仅用于内置示例；自定义项目请关闭 Demo")
                with st.status("Agent 正在运行…", expanded=True) as progress:
                    live = st.empty()

                    def observe(state):
                        live.code(
                            " → ".join(event.action.value for event in state.history),
                            wrap_lines=True,
                        )
                        progress.update(
                            label=f"{state.current_action.value} · "
                            f"repair_count={state.repair_count} · "
                            f"coverage_round={state.coverage_round}"
                        )

                    state = run_project(
                        project,
                        demo=demo,
                        config=config,
                        target=target.strip() or None,
                        observer=observe,
                    )
                    progress.update(
                        label=state.status.value,
                        state="complete" if state.status.value == "COMPLETED" else "error",
                        expanded=False,
                    )
                st.session_state["run_dir"] = state.run_dir
                st.session_state["run_config"] = (
                    f"Model: {redact(config.llm.model)} · Requested Runner: {runner.title()} · "
                    f"Context Budget: {config.agent.context_max_chars} chars · "
                    f"Coverage: {'Line ' + str(line) + '% / Branch ' + str(branch) + '%' if config.coverage.enabled else 'Disabled'}"
                )
            except (TestPilotError, OSError, ValueError) as exc:
                show_failure(f"{type(exc).__name__}: {redact(str(exc))}", "INPUT / STARTUP")
    if "run_dir" in st.session_state:
        st.caption("运行时配置 · " + st.session_state.get("run_config", "以运行产物为准"))
        show_result(Path(st.session_state["run_dir"]))


if __name__ == "__main__":
    main()
