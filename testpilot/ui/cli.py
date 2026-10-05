import argparse
import sys
from pathlib import Path

from testpilot.agent.state import Status
from testpilot.config import load_config_with_source
from testpilot.errors import TestPilotError
from testpilot.service import run_project


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="TestPilot: project-aware pytest generation agent")
    parser.add_argument("project", type=Path)
    parser.add_argument("--target", help="Project-relative Python module path")
    parser.add_argument("--runner", choices=("docker", "local"))
    parser.add_argument(
        "--demo", action="store_true", help="Explicit offline scripted examples only"
    )
    parser.add_argument(
        "--config", type=Path, help="YAML path; defaults to cwd/config.yaml if present"
    )
    parser.add_argument("--output", type=Path, default=Path("runs"))
    args = parser.parse_args(argv)
    try:
        config, source = load_config_with_source(args.config)
        if args.runner:
            config.execution.preferred_runner = args.runner
        print(f"Config: {source if source is not None else 'built-in defaults'}", flush=True)
        print(
            f"model={config.llm.model}; runner={config.execution.preferred_runner}; "
            f"context_max_chars={config.agent.context_max_chars}",
            flush=True,
        )
        if args.demo:
            print("DEMO MODE — no real LLM API call")

        def progress(state):
            print(state.history[-1].observation, flush=True)

        state = run_project(
            args.project,
            config=config,
            target=args.target,
            demo=args.demo,
            output=args.output,
            observer=progress,
        )
        print(f"Report: {Path(state.run_dir) / 'final_report.md'}")
        for warning in dict.fromkeys(state.warnings):
            print(f"Warning: {warning}")
        if state.error:
            print(state.error, file=sys.stderr)
        return 0 if state.status == Status.COMPLETED else 1
    except (TestPilotError, OSError) as exc:
        print(f"TestPilot: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
