import json
import os
import time
from typing import Protocol, TypeVar

from langchain_core.exceptions import OutputParserException
from langchain_core.messages import HumanMessage
from langchain_core.prompts import ChatPromptTemplate
from langchain_openai import ChatOpenAI
from openai import (
    APIConnectionError,
    APIStatusError,
    APITimeoutError,
    LengthFinishReasonError,
    RateLimitError,
)
from pydantic import BaseModel, ValidationError

from testpilot.config import LLMConfig
from testpilot.environment import load_api_environment
from testpilot.errors import (
    ConfigurationError,
    LLMError,
    LLMOutputTruncatedError,
    LLMOutputValidationError,
    LLMTimeoutError,
)
from testpilot.llm.patches import TestPatch, apply_patch
from testpilot.prompts.tasks import SYSTEM, TASKS
from testpilot.schemas.test_plan import GeneratedTest, TestBundle, TestPlan
from testpilot.tools.test_validator import validate_tests

T = TypeVar("T", bound=BaseModel)


class LLMClient(Protocol):
    def plan(self, context: str) -> TestPlan: ...
    def generate(self, context: str, plan: TestPlan) -> TestBundle: ...
    def repair(self, context: str) -> TestBundle: ...
    def improve(self, context: str) -> TestBundle: ...


class DeepSeekClient:
    def __init__(self, config: LLMConfig, model=None, sleep=time.sleep):
        if model is None:
            load_api_environment()
        key = os.getenv("DEEPSEEK_API_KEY")
        if model is None and not key:
            raise ConfigurationError(
                "未配置 DEEPSEEK_API_KEY：请填写启动目录中的 .env 或设置环境变量；离线演示请显式使用 --demo"
            )
        self.config = config
        self.sleep = sleep
        self.events: list[str] = []
        self.diagnostics: list[dict] = []
        self.model = (
            model
            if model is not None
            else ChatOpenAI(
                model=config.model,
                api_key=key,
                base_url="https://api.deepseek.com",
                timeout=config.timeout_seconds,
                max_retries=0,
                max_tokens=config.max_tokens,
                extra_body={"thinking": {"type": "disabled"}},
            )
        )

    def _call(self, task: str, context: str, schema: type[T], validate=None) -> T:
        prompt = ChatPromptTemplate.from_messages(
            [
                ("system", SYSTEM),
                ("human", "Task: {task}\nJSON schema: {schema}\nContext data:\n{context}"),
            ]
        )
        messages = prompt.invoke(
            {
                "task": TASKS[task],
                "schema": json.dumps(schema.model_json_schema()),
                "context": context,
            }
        ).to_messages()
        error: LLMError = LLMError("LLM request failed")
        for attempt in range(self.config.max_retries + 1):
            diagnostic = {
                "task": task,
                "attempt": attempt + 1,
                "model": self.config.model,
                "max_tokens": self.config.max_tokens,
                "context_chars": len(context),
                "status": "failed",
            }
            self.diagnostics.append(diagnostic)
            try:
                result = self.model.with_structured_output(schema, method="json_mode").invoke(
                    messages, config={"callbacks": []}
                )
                parsed = result if isinstance(result, schema) else schema.model_validate(result)
                if validate is not None:
                    validate(parsed)
                diagnostic.update(status="completed", response_chars=len(parsed.model_dump_json()))
                return parsed
            except LengthFinishReasonError as exc:
                usage = exc.completion.usage
                diagnostic.update(
                    finish_reason="length", usage=usage.model_dump() if usage else None
                )
                error = LLMOutputTruncatedError(
                    f"DeepSeek 输出达到长度上限（llm.max_tokens={self.config.max_tokens}），"
                    "返回 JSON 不完整；请检查 llm_calls.json，缩小目标模块或调整输出预算"
                )
            except LLMOutputValidationError as exc:
                error = exc
            except (ValidationError, OutputParserException, ValueError, TypeError) as exc:
                error = LLMOutputValidationError(
                    f"LLM Structured Output 无效或为空 ({type(exc).__name__})"
                )
            except (APITimeoutError, TimeoutError):
                error = LLMTimeoutError(
                    "DeepSeek API timeout；请检查网络或调大 llm.timeout_seconds"
                )
            except (RateLimitError, APIConnectionError):
                error = LLMError("DeepSeek rate limit 或网络暂时错误")
            except APIStatusError as exc:
                diagnostic["http_status"] = exc.status_code
                if exc.status_code < 500 and exc.status_code not in (408, 429):
                    diagnostic["error_type"] = "LLMError"
                    raise LLMError(
                        f"DeepSeek HTTP {exc.status_code}；请检查 Key、模型和 API 权限"
                    ) from exc
                error = LLMError(f"DeepSeek transient HTTP {exc.status_code}")
            diagnostic["error_type"] = type(error).__name__
            self.events.append(f"{task}: attempt {attempt + 1}: {error}")
            if attempt < self.config.max_retries:
                if isinstance(error, LLMOutputValidationError):
                    messages.append(
                        HumanMessage(
                            content=f"Previous response rejected: {error}. Return concise valid JSON. "
                            "Avoid repetition; preserve meaningful tests. For repair return only "
                            "minimal exact edits, never reproduce the whole file."
                        )
                    )
                self.sleep(min(2**attempt, 8))
        raise error

    def plan(self, context: str) -> TestPlan:
        return self._call("PLAN", context, TestPlan)

    def generate(self, context: str, plan: TestPlan) -> TestBundle:
        return self._call(
            "GENERATE",
            context + "\nPLAN:\n" + plan.model_dump_json(),
            TestBundle,
            validate=lambda bundle: validate_tests(bundle.files),
        )

    def repair(self, context: str) -> TestBundle:
        data = json.loads(context)
        originals = [GeneratedTest.model_validate(item) for item in data["existing_tests"]]
        if len(originals) != 1 or data.get("repair_files") != [originals[0].path]:
            raise LLMOutputValidationError("局部修复需要唯一的原始测试文件和 repair_files")
        original = originals[0]
        patch = self._call(
            "REPAIR_PATCH", context, TestPatch, validate=lambda value: apply_patch(original, value)
        )
        return apply_patch(original, patch)

    def improve(self, context: str) -> TestBundle:
        existing = {
            item["path"].casefold() for item in json.loads(context).get("existing_tests", [])
        }

        def validate(bundle):
            validate_tests(bundle.files)
            if any(test.path.casefold() in existing for test in bundle.files):
                raise LLMOutputValidationError("补测必须使用新的文件名，不得覆盖已有测试")

        return self._call("IMPROVE_COVERAGE", context, TestBundle, validate=validate)
