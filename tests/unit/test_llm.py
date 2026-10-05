import httpx
import pytest
from openai import APIStatusError, APITimeoutError, RateLimitError
from pydantic import ValidationError

from testpilot.config import LLMConfig, load_config
from testpilot.errors import ConfigurationError, LLMError, LLMOutputValidationError, LLMTimeoutError
from testpilot.llm.client import DeepSeekClient
from testpilot.schemas.test_plan import GeneratedTest
from testpilot.tools.test_validator import retain_tests, validate_tests


class ModelStub:
    def __init__(self, outcomes):
        self.outcomes = iter(outcomes)
        self.calls = 0

    def with_structured_output(self, schema, method):
        assert method == "json_mode"
        return self

    def invoke(self, messages, **kwargs):
        self.calls += 1
        value = next(self.outcomes)
        if isinstance(value, Exception):
            raise value
        return value


VALID = {
    "target": "x.py",
    "cases": [
        {
            "category": "normal",
            "description": "zero",
            "target_symbol": "f",
            "input_strategy": "0",
            "expected_behavior": "0",
            "priority": 1,
        }
    ],
}


def test_missing_key(monkeypatch):
    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)
    with pytest.raises(ConfigurationError, match="DEEPSEEK_API_KEY"):
        DeepSeekClient(LLMConfig())


def test_structured_output_retries_then_recovers():
    model = ModelStub([{}, VALID])
    client = DeepSeekClient(LLMConfig(), model=model, sleep=lambda _: None)
    assert client.plan("source").target == "x.py"
    assert model.calls == 2 and len(client.events) == 1


def test_bad_structured_output_limit():
    model = ModelStub([{}, {}, {}])
    client = DeepSeekClient(LLMConfig(), model=model, sleep=lambda _: None)
    with pytest.raises(LLMOutputValidationError):
        client.plan("source")
    assert model.calls == 3


@pytest.mark.parametrize("kind", ["timeout", "rate", "server"])
def test_api_transient_retry(kind):
    request = httpx.Request("POST", "https://api.deepseek.com/chat/completions")
    response = httpx.Response(429 if kind == "rate" else 503, request=request)
    error = (
        APITimeoutError(request=request)
        if kind == "timeout"
        else RateLimitError("limited", response=response, body=None)
        if kind == "rate"
        else APIStatusError("server", response=response, body=None)
    )
    model = ModelStub([error, VALID])
    client = DeepSeekClient(LLMConfig(), model=model, sleep=lambda _: None)
    assert client.plan("data").cases and model.calls == 2


def test_timeout_limit_and_auth_no_retry():
    model = ModelStub([TimeoutError()] * 3)
    with pytest.raises(LLMTimeoutError):
        DeepSeekClient(LLMConfig(), model=model, sleep=lambda _: None).plan("data")
    assert model.calls == 3
    response = httpx.Response(401, request=httpx.Request("POST", "https://api.deepseek.com"))
    model = ModelStub([APIStatusError("bad key", response=response, body=None)])
    with pytest.raises(LLMError, match="401"):
        DeepSeekClient(LLMConfig(), model=model, sleep=lambda _: None).plan("data")
    assert model.calls == 1


@pytest.mark.parametrize(
    "path", ["../test_x.py", "C:/test_x.py", "folder/test_x.py", "test_..\\x.py", "conftest.py"]
)
def test_generated_path_validation(path):
    with pytest.raises(ValidationError):
        GeneratedTest(path=path, content="x")


@pytest.mark.parametrize(
    "content",
    [
        "def test_x(): assert True",
        "def test_x(): assert 1 == 1",
        "x = 1",
        "def test_x(): pytest.skip()",
    ],
)
def test_reject_empty_or_trivial_tests(content):
    with pytest.raises(LLMOutputValidationError):
        validate_tests([GeneratedTest(path="test_x.py", content=content)])
    with pytest.raises(LLMOutputValidationError):
        validate_tests([])


def test_repair_cannot_drop_tests():
    before = [GeneratedTest(path="test_x.py", content="def test_x(): assert f() == 1")]
    after = [GeneratedTest(path="test_x.py", content="def test_other(): assert f() == 1")]
    with pytest.raises(LLMOutputValidationError, match="删除"):
        retain_tests(before, after)


def test_bad_config_is_friendly(tmp_path):
    file = tmp_path / "bad.yaml"
    file.write_text("execution:\n  timeout_seconds: -1\n")
    with pytest.raises(ConfigurationError):
        load_config(file)
    file.write_text("unknown_option: 2\n")
    with pytest.raises(ConfigurationError):
        load_config(file)


@pytest.mark.parametrize("value", [512, 16384, 50000, 393216])
def test_supported_output_budgets(tmp_path, value):
    file = tmp_path / "config.yaml"
    file.write_text(f"llm:\n  max_tokens: {value}\n", encoding="utf-8")
    assert load_config(file).llm.max_tokens == value


@pytest.mark.parametrize("value,detail", [(511, "512"), (393217, "393216"), ("invalid", "integer")])
def test_invalid_output_budget_identifies_field_and_constraint(tmp_path, value, detail):
    file = tmp_path / "config.yaml"
    file.write_text(f"llm:\n  max_tokens: {value}\n", encoding="utf-8")
    with pytest.raises(ConfigurationError) as caught:
        load_config(file)
    assert "llm.max_tokens" in str(caught.value)
    assert detail in str(caught.value)


def test_config_validation_does_not_echo_secret_values(tmp_path):
    file = tmp_path / "config.yaml"
    file.write_text("llm:\n  api_key: secret-not-in-environment\n", encoding="utf-8")
    with pytest.raises(ConfigurationError) as caught:
        load_config(file)
    assert "llm.api_key" in str(caught.value)
    assert "secret-not-in-environment" not in str(caught.value)


def test_50000_budget_is_passed_to_model_unchanged(monkeypatch):
    captured = {}
    monkeypatch.setenv("DEEPSEEK_API_KEY", "unit-test-key")
    monkeypatch.setattr(
        "testpilot.llm.client.ChatOpenAI", lambda **kwargs: captured.update(kwargs) or object()
    )
    DeepSeekClient(LLMConfig(max_tokens=50000))
    assert captured["max_tokens"] == 50000
