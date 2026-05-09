# 纳斯达克 ETF 华夏（513300）监控 — 已知边界

## Cron 与「标准 M 时点」

- 现网过程任务使用分钟级 cron（`:15/:45`）与 `PROCESS` 时间窗映射 M1–M6，与教科书式的 9:40 / 11:30 等时点可能存在**数十分钟级偏差**。
- 是否调整 cron 取决于 Phase 6 回测对模式 A 信号敏感度的量化结论。
- **脚本**：`scripts/compare_nasdaq_cron_vs_v3_buckets.py` 打印各 cron 触发时刻的 `PROCESS` 映射；可编辑脚本内 `V3_REFERENCE_MP` 与贵司 v3 表对齐后再比对。

## 数据源边界

- **不包含** QQQ 官方净申赎、美股期权 Put/Call、杠杆 ETF 资金流等因子，除非采集插件提供契约化 `tool_*` 并在 `schema_registry` 登记。
- **USD/CNH**：`global_spot` 请求 **CNH=X**（与 Yahoo 常见符号对齐）；写入 `analysis.global_risk_snapshot.usd_cnh`。若插件返回缺行则 `usd_cnh_quality=degraded`，不做数值捏造。

## 次日开盘预测（模式 B）

- **M7**：全量路径（宏观事件检索 + 可选 LLM + 溢价调制 + `premium_risk` 并入有效事件风险）。
- **M1–M6**：`predictor_run_kind=intraday_next_open_preview`，`_meta.quality_status` 同步为 **`intraday_next_open_preview`**（非 degraded 时）；跳过 Tavily/YF 与 LLM；概率路径为 **rule→premium→（仅 M7）LLM→收缩**。
- **LLM 缓存**：进程内 TTL 默认 **2 小时**，避免跨会话误用。

## 执行成本

- 未建模买卖价差、冲击成本与 QDII 申赎摩擦；与自营交易台生产系统不对标。
