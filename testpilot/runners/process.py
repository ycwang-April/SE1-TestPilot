"""Bounded subprocess execution with process-tree cleanup and capped output."""

import os
import signal
import subprocess
import tempfile
import time
from pathlib import Path


def run_process(
    args: list[str], cwd: Path, env: dict[str, str], timeout: float, output_limit: int = 16000
) -> tuple[int, str, str, bool, float]:
    started = time.monotonic()
    timed_out = False
    with tempfile.TemporaryFile() as out, tempfile.TemporaryFile() as err:
        options = (
            {"creationflags": subprocess.CREATE_NEW_PROCESS_GROUP}
            if os.name == "nt"
            else {"start_new_session": True}
        )
        proc = subprocess.Popen(args, cwd=cwd, env=env, stdout=out, stderr=err, **options)
        try:
            proc.wait(timeout=timeout)
        except subprocess.TimeoutExpired:
            timed_out = True
            if os.name == "nt":
                subprocess.run(
                    ["taskkill", "/PID", str(proc.pid), "/T", "/F"],
                    capture_output=True,
                    timeout=10,
                    check=False,
                )
            else:
                os.killpg(proc.pid, signal.SIGKILL)
            proc.kill()
            proc.wait(timeout=10)

        def tail(handle):
            size = handle.tell()
            handle.seek(max(0, size - output_limit))
            prefix = "[earlier output truncated]\n" if size > output_limit else ""
            return prefix + handle.read().decode("utf-8", errors="replace")

        return proc.returncode, tail(out), tail(err), timed_out, time.monotonic() - started


def execution_env(work: Path) -> dict[str, str]:
    # Do not pass API keys, proxy credentials, PYTEST_ADDOPTS or tracing settings to tested code.
    allowed = {"PATH", "SYSTEMROOT", "WINDIR", "TEMP", "TMP", "COMSPEC", "PATHEXT"}
    env = {k: v for k, v in os.environ.items() if k.upper() in allowed}
    env.update(
        {
            "PYTHONPATH": os.pathsep.join([str(work), str(work / "src")]),
            "PYTHONIOENCODING": "utf-8",
            "PYTEST_DISABLE_PLUGIN_AUTOLOAD": "1",
            "PYTHONDONTWRITEBYTECODE": "1",
            "HOME": str(work),
            "USERPROFILE": str(work),
        }
    )
    return env
