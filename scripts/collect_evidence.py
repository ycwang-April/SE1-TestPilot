"""Run explicit demos and retain small, path-redacted reviewer evidence."""

import json
import sys
import tempfile
from pathlib import Path

from testpilot.agent.state import Status
from testpilot.service import run_project

ROOT = Path(__file__).resolve().parents[1]


def main() -> None:
    summary = []
    for example in ("basic", "multi_module", "edge_cases"):
        state = run_project(ROOT / "examples" / example, demo=True, output=ROOT / "runs")
        source = Path(state.run_dir)
        destination = ROOT / "docs" / "evidence" / example
        for file in source.rglob("*"):
            if not file.is_file() or file.suffix not in (".json", ".md", ".py"):
                continue
            text = file.read_text(encoding="utf-8")
            for original, replacement in (
                (str(ROOT), "<PROJECT>"),
                (str(Path(tempfile.gettempdir())), "<TEMP>"),
            ):
                text = text.replace(original.replace("\\", "\\\\"), replacement)
                text = text.replace(original, replacement).replace(
                    original.replace("\\", "/"), replacement
                )
            target = destination / file.relative_to(source)
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(text, encoding="utf-8")
        summary.append(
            {
                "example": example,
                "status": state.status.value,
                "backend": state.execution_result.backend if state.execution_result else None,
                "passed": state.execution_result.passed if state.execution_result else None,
                "repair_rounds": state.repair_count,
                "coverage_rounds": state.coverage_round,
                "coverage": state.coverage.model_dump() if state.coverage else None,
            }
        )
        if state.status != Status.COMPLETED:
            raise RuntimeError(f"Demo failed: {example}: {state.error}")
    (ROOT / "docs" / "evidence" / "examples-summary.json").write_text(
        json.dumps(
            {"python": sys.version, "demo": True, "examples": summary}, ensure_ascii=False, indent=2
        ),
        encoding="utf-8",
    )
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
