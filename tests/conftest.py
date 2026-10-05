import os
import socket
import tempfile
from pathlib import Path

import pytest

from testpilot.config import AppConfig
from testpilot.schemas.test_plan import GeneratedTest


@pytest.hookimpl(tryfirst=True)
def pytest_configure(config):
    """Avoid shared Windows temp/cache directories owned by another execution account."""
    directory = tempfile.TemporaryDirectory(prefix="testpilot-pytest-")
    config.add_cleanup(directory.cleanup)
    root = Path(directory.name)
    if config.option.basetemp is None:
        config.option.basetemp = str(root / "fixtures")
    # Run before cacheprovider's configure hook. Explicit ini / -o settings still win.
    config.inicfg.setdefault("cache_dir", str(root / "cache"))


@pytest.fixture(autouse=True)
def offline_by_default(request, monkeypatch):
    """A real API call requires both explicit integration opt-in and a key."""
    # Unit tests must never read the developer's real .env file.
    monkeypatch.setenv("TESTPILOT_LOAD_DOTENV", "0")
    enabled = (
        request.node.get_closest_marker("integration")
        and os.getenv("TESTPILOT_RUN_INTEGRATION") == "1"
    )
    if not enabled:
        original_connect = socket.socket.connect
        original_create = socket.create_connection

        def allowed(address):
            return isinstance(address, tuple) and address[0] in ("127.0.0.1", "::1", "localhost")

        def connect(sock, address):
            # Windows asyncio creates a loopback socket pair even for in-process UI tests.
            if allowed(address):
                return original_connect(sock, address)
            raise AssertionError("Unit tests must not access the network")

        def create(address, *args, **kwargs):
            if allowed(address):
                return original_create(address, *args, **kwargs)
            raise AssertionError("Unit tests must not access the network")

        monkeypatch.setattr(socket.socket, "connect", connect)
        monkeypatch.setattr(socket, "create_connection", create)
    monkeypatch.delenv("LANGCHAIN_TRACING_V2", raising=False)
    monkeypatch.delenv("LANGSMITH_TRACING", raising=False)


@pytest.fixture
def project(tmp_path):
    directory = tmp_path / "project"
    directory.mkdir()
    (directory / "sample.py").write_text(
        "def absolute(x):\n    if x < 0:\n        return -x\n    return x\n", encoding="utf-8"
    )
    return directory


@pytest.fixture
def local_config():
    config = AppConfig()
    config.execution.preferred_runner = "local"
    return config


@pytest.fixture
def example_root():
    return Path(__file__).resolve().parents[1] / "examples"


@pytest.fixture
def good_tests():
    return [
        GeneratedTest(
            path="test_sample.py",
            content="""from sample import absolute
def test_absolute():
    assert absolute(-2) == 2
    assert absolute(0) == 0
    assert absolute(3) == 3
""",
        )
    ]
