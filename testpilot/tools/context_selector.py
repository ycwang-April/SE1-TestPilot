import json
from pathlib import Path

from testpilot.agent.state import AgentState
from testpilot.errors import ProjectAnalysisError
from testpilot.tools.file_reader import FileReader


class ContextSelector:
    """Select target source and direct dependencies, with a hard total size bound."""

    def __init__(self, max_chars: int):
        self.max_chars = max_chars

    def select(
        self,
        state: AgentState,
        action: str,
        targets: list[str],
        *,
        repair_file: str | None = None,
        validation_feedback: str | None = None,
    ) -> str:
        related = sorted(
            {dep for t in targets for dep in state.project_index[t].internal_dependencies}
            - set(targets)
        )
        data = {
            "action": action,
            "targets": targets,
            "structure": state.repository.project_structure[:150] if state.repository else [],
            "source": {t: FileReader().read(Path(state.project_path), t) for t in targets},
            "ast": {t: state.project_index[t].model_dump() for t in targets},
            "related_signatures": {t: state.project_index[t].model_dump() for t in related},
            "related_source": {t: FileReader().read(Path(state.project_path), t) for t in related},
            "quality_policy": {
                "goal": "distinct behavior, not number of tests",
            },
        }
        if action in ("PLAN", "GENERATE"):
            data["existing_plans"] = [
                p.model_dump() for p in state.test_plan if p.target not in targets
            ]
        if action == "GENERATE":
            data["existing_tests"] = [t.model_dump() for t in state.generated_tests]
        if action in ("REPAIR", "IMPROVE_COVERAGE"):
            data["existing_tests"] = [t.model_dump() for t in state.generated_tests]
            data["execution"] = (
                state.execution_result.model_dump(exclude={"coverage_data"})
                if state.execution_result
                else None
            )
            data["coverage"] = state.coverage.model_dump() if state.coverage else None
        if action == "REPAIR" and repair_file is not None:
            data["repair_files"] = [repair_file]
            data["existing_tests"] = [
                t.model_dump() for t in state.generated_tests if t.path == repair_file
            ]
            data["preserved_files"] = [
                t.path for t in state.generated_tests if t.path != repair_file
            ]
            data["validation_feedback"] = validation_feedback
        result = json.dumps(data, ensure_ascii=False)
        if len(result) > self.max_chars:
            raise ProjectAnalysisError(
                f"所选上下文 {len(result)} 字符超过预算 {self.max_chars}；请用 --target 缩小范围或调大 context_max_chars"
            )
        return result
