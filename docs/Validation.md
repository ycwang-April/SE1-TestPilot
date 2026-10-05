# 历史验收记录

当前配置已更新为 DeepSeek V4.1 Flash（API 名称 `deepseek-flash`），Docker 已安装，API Key 已由用户配置。下面的数字保留为早期验收记录，不代表新模型或当前 Docker 环境的运行结果；更新后的真实 API 与容器链路需另行验证。

日期：2026-10-04（Asia/Shanghai）。环境：Windows，Python 3.13.9。本次验收的运行依赖安装在仓库外的临时虚拟环境。

## 结果

| 检查 | 实际结果 |
|---|---|
| 可安装性 | `pip install -e . --no-deps --no-build-isolation` 成功，已安装 `testpilot --help` 可用 |
| Ruff | `ruff check .`、`ruff format --check .` 通过 |
| 自动测试 | **87 passed, 1 skipped**，约 26.64 秒 |
| 自身语句/行覆盖率 | **1032 / 1070 = 96.45%** |
| 自身分支覆盖率 | **232 / 256 = 90.63%** |
| pytest-cov 综合口径 | 95.32%（行和分支合并分母，不等于单独的行覆盖率） |
| LangGraph graph / nodes | 本次测试两模块覆盖率均为 100% |
| 真实 DeepSeek 集成 | 早期验收因未配置 Key 而 SKIPPED；当前已配置，新模型链路待验证 |
| 真实 Docker 容器 | 当前已安装；早期验收未运行真实容器，当前容器链路待验证 |
| Docker fallback | 三个正式 Demo 均实际回退 Local，报告保留原因与 host isolation disabled |
| Docker Mock 测试 | 缺安装、daemon 失败/超时、禁止回退、隔离参数、依赖安装失败/超时、finally 清理 |
| Web | Streamlit AppTest 完整运行 edge_cases，最终显示 9 passed |
| 输入保护 | 真实子进程测试前后源项目字节一致；原 pytest 配置和 conftest 不参与生成测试执行 |

机器可读汇总：[self-test-summary.json](evidence/self-test-summary.json)。完整 test case JUnit：[self-tests.xml](evidence/self-tests.xml)。测试是一次真实运行结果，不是保证所有未来平台和项目都成功。

执行命令：

```bash
python -m ruff check .
python -m ruff format --check .
python -m pytest --cov=testpilot --cov-branch --cov-report=term-missing --cov-report=json:runs/self-coverage.json --junitxml=runs/self-tests.xml -q
python scripts/collect_evidence.py
```

`pytest` 默认不调用真实 API。缺省集成测试采用 Key + `TESTPILOT_RUN_INTEGRATION=1` 双重门控，防止有 Key 的开发者运行普通测试时意外付费。

## 示例观察

| 示例 | 首次执行 | 反馈 | 最终执行 | 目标行 / 分支 |
|---|---|---|---|---|
| basic | 7 passed | 无需修复/补测 | 7 passed | 100% / 100% |
| multi_module | 11 passed | 三个模块共同执行 | 11 passed | 100% / 100% |
| edge_cases | 1 failed | 1 次修复，随后 1 次补测 | 9 passed | 100% / 100% |

edge_cases 的第一次断言为 `shipping_fee(1) == 99`。真实执行返回 AssertionError，Demo 修复脚本仅在收到该真实失败观察后改为符合源码契约的 5。再次运行通过，但行覆盖率 54.55%、分支覆盖率 37.50%，Controller 选择补测。追加参数化边界、express 和异常用例后达到 100%。

证据：[trace](evidence/edge_cases/trace.json)、[第 1 轮失败](evidence/edge_cases/rounds/01/execution_result.json)、[第 2 轮 coverage](evidence/edge_cases/rounds/02/coverage_result.json)、[第 3 轮 coverage](evidence/edge_cases/rounds/03/coverage_result.json)、[最终报告](evidence/edge_cases/final_report.md)。

所有示例均明确为 **DEMO MODE — no real LLM API call**。固定模型响应与真实执行分开陈述，不把 Mock 结果作为 DeepSeek 或 Docker 的真实验证。

## 已验证边界

1. 无目录、空目录、无 Python、源码 SyntaxError、无效 target、malformed pyproject。
2. FileReader 越界和文件大小限制，ZIP 损坏、路径穿越、Windows 特殊路径、符号链接、大小写冲突和条目上限。
3. 缺 Key、API timeout、429/503、认证错误、非法 Structured Output、多次失败后停止。
4. 空测试、恒真断言、危险文件名、修复删测试、全部 skip 不得视为成功。
5. 真正运行得到的 ImportError、AssertionError、SyntaxError、pytest timeout。
6. 依赖缺失和不支持的安装指令，Local 禁止自动安装。
7. Docker 初始化失败、本地回退、回退禁用、安装及清理 Mock。
8. Coverage 数据缺失、不足触发补测、补测达上限、repair 达上限、coverage 关闭。
9. CLI 成功/失败退出码、失败报告落盘、API Key 脱敏、子进程不继承 API Key。
10. Streamlit 真实核心闭环，跨模块上下文与源码保持不变。

## 验证限制

本次验收尚未执行：真实 API 集成、真实 Docker、Linux/macOS 实机、远程 CI。CI 配置已提供，不把未运行的 CI 宣称为通过。
