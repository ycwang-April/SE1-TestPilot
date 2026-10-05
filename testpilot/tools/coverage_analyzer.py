from testpilot.errors import CoverageError
from testpilot.schemas.execution import CoverageResult


class CoverageAnalyzer:
    def analyze(self, data: dict | None, targets: list[str]) -> CoverageResult:
        try:
            if not data or not isinstance(data.get("files"), dict):
                raise ValueError("missing files")
            files = {p.replace("\\", "/").removeprefix("./"): v for p, v in data["files"].items()}
            selected = {p: files[p] for p in targets}
            for entry in selected.values():
                summary = entry["summary"]
                for covered, total in (
                    ("covered_lines", "num_statements"),
                    ("covered_branches", "num_branches"),
                ):
                    if (
                        type(summary[covered]) is not int
                        or type(summary[total]) is not int
                        or not 0 <= summary[covered] <= summary[total]
                    ):
                        raise ValueError("invalid coverage counts")
            totals = {
                key: sum(f["summary"][key] for f in selected.values())
                for key in ("num_statements", "covered_lines", "num_branches", "covered_branches")
            }
            return CoverageResult(
                line_coverage=100 * totals["covered_lines"] / totals["num_statements"]
                if totals["num_statements"]
                else 100,
                branch_coverage=100 * totals["covered_branches"] / totals["num_branches"]
                if totals["num_branches"]
                else 100,
                missing_lines={p: f["missing_lines"] for p, f in selected.items()},
                missing_branches={p: f["missing_branches"] for p, f in selected.items()},
            )
        except (KeyError, TypeError, ValueError) as exc:
            raise CoverageError(
                "coverage 数据缺失或格式无效，无法确认覆盖率；检查 pytest-cov 和目标路径"
            ) from exc
