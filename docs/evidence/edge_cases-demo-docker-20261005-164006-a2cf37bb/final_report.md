# TestPilot Run Report

- Project: edge_cases
- Status: COMPLETED
- Mode: DEMO MODE — no real LLM API call
- Modules / functions / classes: 1 / 1 / 0
- Generated test functions: 3
- Collected pytest cases: 9
- Passed / failed / errors / skipped: 9 / 0 / 0 / 0
- Initial passed / failed / errors: 0 / 1 / 0
- Final passed / failed / errors: 9 / 0 / 0
- Repair rounds: 1
- Coverage improvement rounds: 1
- Execution Backend: Docker
- Counts: generated_test_functions counts definitions; collected_test_cases counts pytest items after parametrization. generated_tests is a compatibility alias for function count. Errors include collection/setup/teardown errors; counts need not sum to collected items. Unavailable collection counts are null.
- Line coverage: 100.00%
- Branch coverage: 100.00%

## Warnings and limitations

- Plan deduplicated: shipping.py: shipping (boundary)
- Plan deduplicated: shipping.py: shipping (exception)
- Plan deduplicated: shipping.py: shipping (invalid)
- Plan deduplicated: shipping.py: shipping (branch)
- Plan deduplicated: shipping.py: shipping (interaction)
- 高覆盖率不等于高测试质量；断言仍需人工复核
- LocalRunner 不提供宿主隔离
- 只运行新生成的测试；已有测试被识别但不合并执行
- 上下文和复制大小有限制，超限应使用 --target

## Generated tests

- [generated_tests/test_shipping.py](generated_tests/test_shipping.py)
- [generated_tests/test_shipping_extra.py](generated_tests/test_shipping_extra.py)
