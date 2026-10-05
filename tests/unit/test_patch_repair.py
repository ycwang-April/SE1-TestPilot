import json

import pytest
from openai import LengthFinishReasonError
from openai.types.chat import ChatCompletion

from testpilot.config import LLMConfig
from testpilot.errors import LLMOutputTruncatedError, LLMOutputValidationError
from testpilot.llm.client import DeepSeekClient
from testpilot.llm.patches import TestPatch as Patch
from testpilot.llm.patches import apply_patch
from testpilot.schemas.test_plan import GeneratedTest
from testpilot.schemas.test_plan import TestPlan as Plan
from testpilot.tools.test_validator import retain_tests, validate_tests

SOURCE = "from sample import f\ndef test_a(): assert f(-1) == -1\ndef test_b(): assert f(2) == 2\n"
ORIGINAL = GeneratedTest(path="test_sample.py", content=SOURCE)
CONTEXT = json.dumps({"existing_tests": [ORIGINAL.model_dump()], "repair_files": [ORIGINAL.path]})
VALID = {"path": ORIGINAL.path, "edits": [{"old": "f(-1) == -1", "new": "f(-1) == 1"}]}


class Model:
    def __init__(self, outcomes):
        self.outcomes = iter(outcomes)
        self.messages = []

    def with_structured_output(self, schema, method):
        return self

    def invoke(self, messages, **kwargs):
        self.messages.append(list(messages))
        value = next(self.outcomes)
        if isinstance(value, Exception):
            raise value
        return value


def truncated():
    return LengthFinishReasonError(
        completion=ChatCompletion(
            id="fake",
            created=0,
            model="fake",
            object="chat.completion",
            choices=[
                {
                    "index": 0,
                    "finish_reason": "length",
                    "message": {"role": "assistant", "content": "{"},
                }
            ],
            usage={"completion_tokens": 512, "prompt_tokens": 100, "total_tokens": 612},
        )
    )


def test_minimal_patch_preserves_every_other_byte():
    bundle = apply_patch(ORIGINAL, Patch.model_validate(VALID))
    assert bundle.files[0].content == SOURCE.replace("f(-1) == -1", "f(-1) == 1")
    assert ORIGINAL.content == SOURCE


@pytest.mark.parametrize(
    "patch",
    [
        {"path": "../test_bad.py", "edits": VALID["edits"]},
        {"path": ORIGINAL.path, "edits": [{"old": "assert", "new": "pass #"}]},
        {"path": ORIGINAL.path, "edits": [{"old": "absent", "new": "pass"}]},
        {"path": ORIGINAL.path, "edits": [VALID["edits"][0], VALID["edits"][0]]},
        {"path": ORIGINAL.path, "edits": [{"old": "def test_b(): assert f(2) == 2\n", "new": ""}]},
        {"path": ORIGINAL.path, "edits": [{"old": "f(-1) == -1", "new": "True"}]},
    ],
)
def test_invalid_patch_cannot_modify_original(patch):
    with pytest.raises(LLMOutputValidationError):
        apply_patch(ORIGINAL, Patch.model_validate(patch))
    assert ORIGINAL.content == SOURCE


def test_patch_validation_feedback_retries():
    invalid = {"path": ORIGINAL.path, "edits": [{"old": "assert", "new": "pass #"}]}
    model = Model([invalid, VALID])
    client = DeepSeekClient(LLMConfig(), model=model, sleep=lambda _: None)
    assert "f(-1) == 1" in client.repair(CONTEXT).files[0].content
    assert "精确出现一次" in model.messages[1][-1].content
    assert [item["status"] for item in client.diagnostics] == ["failed", "completed"]


def test_truncation_retries_with_feedback_and_records_usage():
    model = Model([truncated(), VALID])
    client = DeepSeekClient(LLMConfig(max_tokens=512), model=model, sleep=lambda _: None)
    assert client.repair(CONTEXT).files[0].content != SOURCE
    assert client.diagnostics[0]["finish_reason"] == "length"
    assert client.diagnostics[0]["usage"]["completion_tokens"] == 512
    assert "长度上限" in model.messages[1][-1].content


def test_truncation_exhaustion_is_actionable_and_bounded():
    model = Model([truncated(), truncated()])
    client = DeepSeekClient(LLMConfig(max_retries=1), model=model, sleep=lambda _: None)
    with pytest.raises(LLMOutputTruncatedError, match="llm.max_tokens") as caught:
        client.repair(CONTEXT)
    assert len(model.messages) == 2
    assert "长度上限" in str(caught.value)


def test_retention_distinguishes_class_methods():
    before = GeneratedTest(
        path="test_x.py",
        content="class TestA:\n def test_same(self): assert f()\nclass TestB:\n def test_same(self): assert f()\n",
    )
    after = GeneratedTest(
        path="test_x.py", content="class TestA:\n def test_same(self): assert f()\n"
    )
    with pytest.raises(LLMOutputValidationError, match="TestB.test_same"):
        retain_tests([before], [after])


def test_retention_rejects_lost_parameter_rows():
    before = GeneratedTest(
        path="test_x.py",
        content="@pytest.mark.parametrize('x', [1, 2, 3])\ndef test_x(x): assert f(x)\n",
    )
    after = before.model_copy(update={"content": before.content.replace("[1, 2, 3]", "[1, 2]")})
    with pytest.raises(LLMOutputValidationError, match="参数化"):
        retain_tests([before], [after])


def test_generate_retries_semantically_invalid_output():
    model = Model(
        [
            {"files": [{"path": ORIGINAL.path, "content": "def test_x(): assert True"}]},
            {"files": [ORIGINAL.model_dump()]},
        ]
    )
    client = DeepSeekClient(LLMConfig(), model=model, sleep=lambda _: None)
    plan = Plan(
        target="sample.py",
        cases=[
            {
                "category": "normal",
                "description": "f",
                "target_symbol": "f",
                "input_strategy": "signed",
                "expected_behavior": "nonnegative",
            }
        ],
    )
    assert client.generate("{}", plan).files == [ORIGINAL]
    assert "恒真断言" in model.messages[1][-1].content


def test_improvement_retries_colliding_filename():
    addition = ORIGINAL.model_copy(update={"path": "test_additional.py"})
    model = Model([{"files": [ORIGINAL.model_dump()]}, {"files": [addition.model_dump()]}])
    client = DeepSeekClient(LLMConfig(), model=model, sleep=lambda _: None)
    assert client.improve(CONTEXT).files == [addition]
    assert "新的文件名" in model.messages[1][-1].content


def test_reject_assertion_hidden_by_or_true():
    test = GeneratedTest(path="test_x.py", content="def test_x(): assert f() == 42 or True")
    with pytest.raises(LLMOutputValidationError, match="恒真断言"):
        validate_tests([test])


def test_real_boolean_behavior_is_not_mistaken_for_constant_truth():
    validate_tests([GeneratedTest(path="test_x.py", content="def test_x(): assert f() or g()")])
