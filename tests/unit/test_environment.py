import os

import pytest

from testpilot.environment import load_api_environment
from testpilot.errors import ConfigurationError


@pytest.fixture
def env_file(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)
    monkeypatch.delenv("TESTPILOT_LOAD_DOTENV", raising=False)
    yield tmp_path / ".env"
    # The loader writes directly to os.environ; remove its value before monkeypatch restores it.
    os.environ.pop("DEEPSEEK_API_KEY", None)


def test_load_key_from_launch_directory(env_file):
    env_file.write_text('DEEPSEEK_API_KEY="test-fixture-key"\n', encoding="utf-8-sig")
    load_api_environment()
    assert os.environ["DEEPSEEK_API_KEY"] == "test-fixture-key"


def test_existing_environment_takes_precedence(env_file, monkeypatch):
    env_file.write_text("DEEPSEEK_API_KEY=file-fixture-key\n")
    monkeypatch.setenv("DEEPSEEK_API_KEY", "shell-fixture-key")
    load_api_environment()
    assert os.environ["DEEPSEEK_API_KEY"] == "shell-fixture-key"


def test_disable_file_loading(env_file, monkeypatch):
    env_file.write_text("DEEPSEEK_API_KEY=file-fixture-key\n")
    monkeypatch.setenv("TESTPILOT_LOAD_DOTENV", "0")
    load_api_environment()
    assert "DEEPSEEK_API_KEY" not in os.environ


def test_does_not_load_other_variables_or_expand_values(env_file, monkeypatch):
    monkeypatch.delenv("TESTPILOT_UNRELATED", raising=False)
    env_file.write_text("DEEPSEEK_API_KEY=literal-${NOT_EXPANDED}\nTESTPILOT_UNRELATED=ignored\n")
    load_api_environment()
    assert os.environ["DEEPSEEK_API_KEY"] == "literal-${NOT_EXPANDED}"
    assert "TESTPILOT_UNRELATED" not in os.environ


@pytest.mark.parametrize("contents", [None, "", "DEEPSEEK_API_KEY=\n", "OTHER=value\n"])
def test_missing_or_empty_key(env_file, contents):
    if contents is not None:
        env_file.write_text(contents)
    load_api_environment()
    assert "DEEPSEEK_API_KEY" not in os.environ


def test_encoding_error_is_actionable(env_file):
    env_file.write_bytes(b"\xff\xfeinvalid")
    with pytest.raises(ConfigurationError, match="UTF-8"):
        load_api_environment()


def test_real_adapter_loads_key_before_initializing_model(env_file, monkeypatch):
    from testpilot.config import LLMConfig
    from testpilot.llm.client import DeepSeekClient

    env_file.write_text("DEEPSEEK_API_KEY=file-fixture-key\n")
    options = {}

    def fake_model(**kwargs):
        options.update(kwargs)
        return object()

    monkeypatch.setattr("testpilot.llm.client.ChatOpenAI", fake_model)
    DeepSeekClient(LLMConfig())
    assert options["api_key"] == "file-fixture-key"
