# TestPilot Run Report

- Project: advanced_project
- Status: COMPLETED
- Mode: DeepSeek
- Modules / functions / classes: 6 / 11 / 11
- Generated test functions: 82
- Collected pytest cases: 108
- Passed / failed / errors / skipped: 108 / 0 / 0 / 0
- Initial passed / failed / errors: 106 / 2 / 0
- Final passed / failed / errors: 108 / 0 / 0
- Repair rounds: 1
- Coverage improvement rounds: 0
- Execution Backend: Docker
- Counts: generated_test_functions counts definitions; collected_test_cases counts pytest items after parametrization. generated_tests is a compatibility alias for function count. Errors include collection/setup/teardown errors; counts need not sum to collected items. Unavailable collection counts are null.
- Line coverage: 100.00%
- Branch coverage: 100.00%

## Warnings and limitations

- 高覆盖率不等于高测试质量；断言仍需人工复核
- LocalRunner 不提供宿主隔离
- 只运行新生成的测试；已有测试被识别但不合并执行
- 上下文和复制大小有限制，超限应使用 --target

## Generated tests

- [generated_tests/test_coupon.py](generated_tests/test_coupon.py)
- [generated_tests/test_errors.py](generated_tests/test_errors.py)
- [generated_tests/test_inventory.py](generated_tests/test_inventory.py)
- [generated_tests/test_models.py](generated_tests/test_models.py)
- [generated_tests/test_order_service.py](generated_tests/test_order_service.py)
- [generated_tests/test_pricing.py](generated_tests/test_pricing.py)
