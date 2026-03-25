# 宽基ETF巡检快报 - 日内波动区间收敛说明（缓存口径）

## 1. 为什么需要这份说明

`tool_predict_intraday_range` 已经做了日内区间“收敛”（`range_pct` 约束 + `confidence` 收敛）。但你的“宽基ETF巡检快报”并不是直接复用 `tool_predict_intraday_range` 的输出，而是读取当天的缓存文件：

- `data/volatility_ranges/{date}.json`

因此如果缓存的生成链路仍在“多周期（multi-period）”里按旧口径输出，就会出现：

- 快新闻仍然“区间偏宽”
- 置信度偏乐观

本次优化把收敛逻辑下沉到缓存生成源头，使得只要缓存是由本仓库当前代码生成的，宽基ETF巡检快报读取到的数据也会同步收敛。

---

## 2. 收敛发生在缓存生成源头（而不是仅在工具输出）

缓存生成入口为 `src/volatility_range.py -> calculate_volatility_ranges()`。

在 `calculate_volatility_ranges()` 内部，会读取 `config.yaml` 的如下配置，并对输出做统一收敛：

`config.yaml -> signal_params -> intraday_monitor_510300 -> volatility`

- `min_intraday_pct`：单日有效波动下限（默认 `0.005`，即 `0.5%`）
- `max_intraday_pct`：单日合理波动上限（默认 `0.04`，即 `4%`）

收敛规则（核心口径）：

1. 将 `range_pct` 夹到 `[min_pct, max_pct]`（这里的 `min_pct/max_pct` 为百分比口径）
2. 若 `range_pct` 被夹紧，会以 `current_price` 为中心对称重算 `upper/lower`，并更新 `range_pct`
3. `confidence` 做硬上限：`confidence <= 0.6`
4. 若原始区间已超上限，会进一步降低 `confidence`（避免“区间更宽但置信度更高”的组合再次出现）

---

## 3. 缓存文件格式与可观测字段

缓存文件：`data/volatility_ranges/{date}.json`

> `load_volatility_ranges()` 的返回是“列表”，每条记录对应一次生成（同一天可能多次追加）。

调试时建议优先检查以下路径（新格式）：

- `underlyings -> 510300 -> etf_range`

或兼容旧格式（单一 `etf_range`）：

- 顶层 `etf_range`

本次收敛会为 `index_range/etf_range` 写入以下诊断字段（用于验证是否发生夹紧）：

- `clamp_applied`：是否触发收敛夹紧（布尔）
- `clamp_bounds_pct`：夹紧上下界百分比（如 `{"min_pct":0.5,"max_pct":4.0}`）

---

## 4. 与 tool_predict_intraday_range 的口径一致性

你现在的两条链路将使用同一套“收敛口径”：

- `tool_predict_intraday_range`：实时工具输出（同时会被写入 `prediction_records` 供回填/评估）
- 缓存生成（`calculate_volatility_ranges`）：生成 `data/volatility_ranges/{date}.json`（供宽基ETF巡检快报读取）

因此，在验证时更建议同时看：

- 快报读取的缓存：`data/volatility_ranges/{date}.json`
- 工具的预测记录：`data/prediction_records/predictions_{date}.json`

---

## 5. 如何验证“收敛是否生效”（建议你明日/当日直接跑）

验证点 1：缓存区间宽度是否被夹紧

1. 打开 `data/volatility_ranges/{date}.json`
2. 进入 `underlyings -> 510300 -> etf_range`
3. 检查：
   - `range_pct <= max_intraday_pct * 100`（默认 `4.0`）
   - `confidence <= 0.6`
   - `clamp_applied == true`（若当天预测原始区间确实超界）

验证点 2：缓存诊断字段是否存在

- 若能看到 `clamp_applied` / `clamp_bounds_pct`，说明缓存是由新口径生成链路写入的

> 注意：历史日期的缓存不会自动回写；如果你要验证某一天的“旧缓存”，需要重新跑缓存生成链路（或按你们运行习惯覆盖当天文件）。

---

## 6. 新增评估/回填脚本（用于闭环验证）

### 6.1 日内实际区间回填

- 脚本：`scripts/update_intraday_range_actuals.py`
- 目的：把 `predictions_{date}.json` 中未验证的记录补上 `actual_range`，并计算 `hit`
- 典型用法：

```bash
python3 scripts/update_intraday_range_actuals.py --date 20260325
python3 scripts/update_intraday_range_actuals.py --date 20260325 --dry-run
```

会更新：

- `data/prediction_records/predictions_{date}.json`
- SQLite：`data/prediction_records/prediction_records.db`

### 6.2 生成周报（覆盖率/区间宽度等）

- 脚本：`scripts/generate_intraday_range_weekly_report.py`
- 目的：基于 `data/prediction_records/*` 的 `verified` 数据生成周报，并落盘 `data/prediction_reports/`
- 用法：

```bash
python3 scripts/generate_intraday_range_weekly_report.py --week-start 20260324
```

### 6.3 方法分组指标监控（fallback vs minute）

- 脚本：`scripts/monitor_intraday_range_method_metrics.py`
- 目的：
  - 统计最近 N 天各方法的占比（fallback_daily vs minute_multi_period）
  - 对已验证样本计算 `coverage_rate` 与 `average_width_pct`
- 输出：
  - `data/prediction_reports/intraday_range_method_metrics_{start}_{end}.json`
- 用法：

```bash
python3 scripts/monitor_intraday_range_method_metrics.py --days 14
```

---

## 7. 与配置的对应关系速查

- 收敛上限/下限：`config.yaml` 的 `signal_params.intraday_monitor_510300.volatility`
- 缓存读取文件：`data/volatility_ranges/{date}.json`
- 缓存诊断字段：`clamp_applied`、`clamp_bounds_pct`
- 预测评估记录：`data/prediction_records/predictions_{date}.json`

