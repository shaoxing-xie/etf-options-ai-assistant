# 开盘行情分析（9:28）：Cron 与数据不全排查

## 1. 单次复合工具（推荐）

- **工具**：`tool_run_opening_analysis_and_send(mode='prod', fetch_mode='production')`
- **步骤定义**：`workflows/opening_analysis.yaml`（进程内顺序与 `continue_on_failure` 对齐 `plugins/notification/run_opening_analysis.py`）
- **渲染**：`tool_send_analysis_report` → `send_daily_report`（`report_type=opening` 与 `before_open` 共用章节顺序）

本地烟测（不经钉钉）：`python3 tool_runner.py tool_run_opening_analysis_and_send mode=test fetch_mode=test`

## 2. 数据不全 / N/A / 降级时的原则（必读）

**禁止**在未经逐项核对前，把现象笼统归因于「数据采集工具坏了」「网络不稳定」或「接口挂了」。复合工具已在进程内组装 `report_data`，多数缺字段来自 **键路径、合并逻辑、时段口径、可选插件未启用**，而非模糊的「采集层故障」。

建议按下面顺序查根因；只有在前几步排除后，再考虑外网/供应商问题。

## 3. 排查顺序（与日报类任务一致，开盘特化）

1. **单步 `tool_runner`**：对缺失章节对应的 `tool_*` 单独执行，看 `data` 形态与是否含预期嵌套键（是否与 `run_opening_analysis.build_opening_report_data` 的合并键一致）。
2. **映射与模板**：对照 `send_daily_report.py` 中 opening 各 `_build_*_lines`、`_normalize_analysis_payload`、`_resolve_trend_fields` 等读取路径，确认 `report_data` / `analysis` 里字段名一致（含别名）。
3. **分析工具输出**：`tool_analyze_market`（opening）等若返回 `overall_trend`、`report_meta` 等与模板假设不一致，会导致「晨间结论」等长期 N/A——属**契约对齐**问题，不是采集失败。
4. **环境与插件**：资金面等依赖 `openclaw-data-china-stock` 或相关配置时，确认已安装/启用；核对合并后配置与 `DAILY_REPORT_*` 等环境变量是否关闭自动补全或改口径。
5. **交易时段与数据源口径**：盘前/竞价/连续竞价下部分接口字段为空属预期时，应在报告 meta 中显式说明，而非默认「网络不稳」。
6. **外网与供应商**：A50、金龙等若主源失败但有降级摘要，先对照 `overnight_overlay` / `degraded` 字段与工具实现，再判断是否为可持续的外部故障。

## 4. 钉钉与 Gateway

- 分片发送、关键词、加签等问题与巡检任务相同，可参考 `docs/ops/cron_signal_inspection_triage.md` 第 3 节。
- OpenClaw 多轮 JSON 截断主要影响**旧式**「模型拼 report」路径；当前推荐单次复合工具，截断风险已显著降低，若仍缺块应回到第 3 节字段核对。
