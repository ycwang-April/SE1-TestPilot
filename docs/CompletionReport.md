# Homework 1 最终完成报告

## 1. 最终目录

```text
hw1/
├── testpilot/
│   ├── agent/          # graph、controller、nodes、Pydantic state
│   ├── tools/          # scan、AST、read、context、coverage、ZIP、dependencies
│   ├── runners/        # base、local、docker、fallback、process、workspace
│   ├── llm/            # DeepSeek adapter、显式 Demo、源码指纹
│   ├── schemas/        # project、test_plan、execution
│   ├── prompts/        # 各阶段系统和任务提示
│   ├── reporting/      # JSON/Markdown 报告、逐轮证据、脱敏
│   ├── ui/             # CLI、Streamlit
│   ├── config.py
│   ├── environment.py  # 加载启动目录 .env，已有环境变量优先
│   └── service.py      # 双入口共享核心
├── tests/
│   ├── unit/           # 工具、LLM、runner、workflow、UI
│   └── integration/    # 显式启用的真实 DeepSeek E2E
├── examples/{basic,multi_module,edge_cases}/
├── docs/
│   ├── evidence/       # 三组真实 Demo 运行、逐轮记录、测试汇总
│   ├── Validation.md
│   └── CompletionReport.md
├── scripts/collect_evidence.py
├── .github/workflows/ci.yml
├── README.md
├── Design.md
├── Dockerfile
├── config.yaml
├── .env.example
├── pyproject.toml
└── requirements.txt
```

本地 `runs/` 保存运行记录，测试缓存和 editable-install 元数据由开发工具自动生成。

## 2–4. 核心架构、Agent Loop 与 Tools

采用单主 Agent，LangGraph StateGraph 以 Pydantic State 为共享记忆，通过 Controller 的 conditional edges 决定 ANALYZE、PLAN、GENERATE、EXECUTE、REPAIR、IMPROVE_COVERAGE、FINISH 或 FAIL。每个动作的工具结果返回 State，再进行决策。API 重试和工作流修复有独立、可配置的预算。

已实现 RepositoryScanner、FileReader、ASTAnalyzer、ContextSelector、CoverageAnalyzer、依赖检查、ZIP 安全解压和统一 TestRunner。DeepSeek 经 LangChain prompt / structured output 调用；CLI/Web 只负责交互。

## 5. 边界情况

覆盖项目路径与语法、空输入、坏 ZIP/zip-slip、依赖缺失、无 Key、API timeout/rate limit/非法结构、生成代码语法错误、ImportError、AssertionError、Docker 缺失/daemon 失败、pytest timeout、coverage 失败、修复/补测耗尽等。详见 Validation.md 和对应测试。

## 6–10. 实际测试、API、Runner、Coverage、Examples

当前模型为 DeepSeek V4.1 Flash（API 名称 `deepseek-flash`），输出上限配置为 16384 tokens。以下测试数字为早期验收记录，当前配置的结果需以重新运行的报告为准。

- 自动测试：**87 passed，1 skipped**，静态检查通过。
- 项目自身覆盖率：行 **96.45%**、分支 **90.63%**。该指标与被测示例覆盖率独立。
- 真实 DeepSeek：API Key 已由用户配置；早期验收跳过真实 API，新模型链路待验证。
- 真实 Docker：已安装；daemon、runner 镜像和真实容器链路待验证。早期 Local fallback 和 Docker Mock 记录仍保留。
- basic：7 passed，行/分支 100%。
- multi_module：11 passed，3 个模块，行/分支 100%。
- edge_cases：首次 1 failed → 修复后 1 passed、覆盖率不足 → 补测后 9 passed、行/分支 100%。
- 三个示例的模型响应为明确标记的 Demo fixture，pytest/coverage 为真实执行。Web AppTest 也跑通同一 edge_cases 核心。

## 11. 文档和评分证据

README 包含安装、配置、CLI/Web、Docker、依赖、Context Memory、两个反馈循环、单测/集成测试、错误处理、Known Limitations 和 Rubric Mapping。Design.md 包含图、状态、工具分工、错误和重试、测试策略及 HW2 扩展。docs/evidence 保存脱敏后的精简运行证据。

## 12. Known Limitations

偏向中小型同步 Python 逻辑，较大上下文需按模块运行；动态导入、复杂依赖管理器、异步系统、大型 Web/GPU/外部服务不保证支持。已有测试被识别但不合并执行。Local 不提供宿主隔离。断言质量检查是启发式，覆盖率不能替代人工评审。暂不支持跨进程 checkpoint 恢复。

真实 API、Docker 和跨平台实机验收尚未完成，不夸大为已验证。

## 13. HW2 复用

State、schemas、确定性工具、Runner、DeepSeek Adapter 和 ArtifactWriter 可直接复用。可将 Plan/Generate、Execute、Repair 分别移入生成、执行、修复 Agent，继续共享 WorkflowState 和上层全局预算。HW1 保持一个主 Agent。
