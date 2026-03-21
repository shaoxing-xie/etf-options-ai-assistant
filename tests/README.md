# 测试与集成脚本说明

## 目录结构

| 路径 | 说明 |
|------|------|
| `test_smoke_tool_runner.py` | `pytest`：`tool_runner` 冒烟（轻量） |
| `test_tick_client.py` | `pytest`：`tick_client` 相关 |
| `integration/` | **非 pytest 默认收集**：长耗时、需网络/缓存的集成脚本（手动或 CI 显式调用） |
| `manual/` | 手工诊断脚本（如 AkShare 原始接口探测；文件名避免 `test_*.py` 以免被 pytest 误收集） |

`integration/` 下脚本**不以** `test_` 开头，避免被 `pytest` 误当作单元测试模块收集（历史文件已重命名）。

---

## 运行方式

在项目根目录：

```bash
# 单元/冒烟（推荐日常）
pytest -q

# 数据管线：串行调用 tool_runner 多个工具（需网络与本地配置）
python3 tests/integration/verify_data_pipeline.py

# 合并工具与别名：覆盖多类 tool_*（耗时可较长）
python3 tests/integration/run_merged_tools_smoke.py

# 工作流：串行执行 workflows/ 下各 step_by_step 脚本
python3 tests/integration/run_all_workflow_tests.py

# 指数开盘接口：直接探测 AkShare 东财/新浪（排障用）
python3 tests/manual/manual_index_opening_apis.py
```

---

## 与 `scripts/` 的区别

- **`tests/`**：验证行为、回归、管线连通性。
- **`scripts/`**：运维、发布门禁、预警轮询等，见 `scripts/README.md`。
