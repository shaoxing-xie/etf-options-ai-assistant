# ETF 轮动：缓存试验结论与「最小方案」建议（待你确认后再改 `etf_rotation_core`）

## 1. 试验目的

验证「延长任务时间」主要来自 **(A) 日线加载/补采** 还是 **(B) 58 指标 CPU**，以决定优先做哪类缓存。

## 2. 试验方法

- 脚本：`scripts/benchmark_etf_rotation_phases.py`（**不改生产逻辑**）。
- 环境：本机一次冷/半冷缓存跑（日志中出现多次 Tushare 拉取与回写 parquet）。
- 命令：

```bash
cd /home/xie/etf-options-ai-assistant
PYTHONPATH=plugins:. python3 scripts/benchmark_etf_rotation_phases.py
# 热缓存后快速抽样：
PYTHONPATH=plugins:. python3 scripts/benchmark_etf_rotation_phases.py --max-symbols 5
```

## 3. 试验结果（一次全池 32 标的）

| 指标 | 数值 |
|------|------|
| 轮动池规模 | **32**（`industry_etf` 15 + `concept_etf` 15 + `extra` 3，去重后） |
| `lookback_days` | 120 |
| `data_need`（由 MA/相关/R² 等推导） | **257** |
| 加载区间（日历回退） | `(20240307, 20260417)` |
| **整段 per_symbol 循环** | **~499 s（约 8.3 min）** |
| 其中 `load_etf_daily_df` 累计 | **~498.5 s（占绝对主导）** |
| `trim_dataframe` 累计 | **~0.008 s** |
| `extract_58_features` 累计（全池） | **~0.54 s** |
| 成功产出 58 特征标的数 | 30（2 只失败/无特征） |

**结论（本轮数据）**：在当前池子与实现下，**58 特征计算几乎不是瓶颈**；耗时主要在 **ETF 日线读盘 + 缓存未命中时的在线补采/多次拉取**。因此：

- **优先优化方向**：提高 **etf_daily parquet 命中率**、减少 **同任务内重复网络请求**、合并/批量化读缓存（若架构允许）。
- **「按日缓存指标列」**：可作为第二阶段；**单独做指标缓存 ROI 偏低**，除非池子扩大到上百只或退化为纯 Python 指标路径。

## 4. 若仍要做「最小指标/特征缓存」（待确认后实施）

### 4.1 缓存键（建议）

统一 JSON 元数据 + parquet 宽表（或单列 feather），主键建议包含**版本**，避免静默错结果：

```
key = hash(
  symbol,
  data_type = "etf_daily",
  bar_freq = "1d",
  adj = <与 read_cache 一致>,
  feature_set = "rotation58_p0_v1",
  engine = "talib|pandas_ta|builtin",
  macd_factor,
  rotation_config_version,   # rotation_config.yaml version 或 mtime
  last_bar_date,              # 标的最后一根已纳入缓存的交易日
)
```

文件名示例：`data/rotation_feature_cache/{symbol}/meta.json` + `features.parquet`。

### 4.2 失效规则

- **`rotation_config.yaml` 的 `version` 或文件 mtime 变化** → 全量失效该配置下所有缓存。
- **`macd_factor` / 指标参数 / score_engine` 变化** → 失效对应 `feature_set` 或整桶。
- **标的复权口径或数据源策略变更** → 失效 `symbol` 或全池。
- **检测到 `read_cache_data` 返回的 `missing_dates` 非空且已补写** → 仅对该 `symbol` 从 `last_bar_date` 起增量重算。

### 4.3 增量重算窗口 **W**（建议保守值）

当前 `extract_58` 使用 MACD(12,26,9)、RSI(14)、ADX(14)、NATR(14)、BBANDS(20,2)。  
尾部重算至少需要覆盖最长 EMA/信号 与 BB 窗口：

- MACD 慢线 26 + 信号 9 → 约 **35** 根以上收盘价参与尾部稳定；
- BBANDS 20；
- 再留 **日历缺口/对齐** 缓冲。

**建议 `W = 120`（交易日）**：实现简单、与常见「四个月级别」尾部重算一致；若以后要抠性能，可降到 **80** 并在回归测试里对比最后一行特征误差。

流程：**读全量 OHLCV（已由 parquet 缓存）→ 仅取最后 `W` 行 → 重算指标 → 合并写回特征表最后一行**。

## 5. 建议实施顺序（供你拍板）

1. **P0（高收益）**：排查 `load_etf_daily_df` 路径上是否存在 **同标的同区间重复拉取**（试验日志里可见连续两次 Tushare 成功同一代码）；能合并为一次则直接省分钟级时间。  
2. **P1**：保证采集任务写满 `etf_daily` 缓存，轮动任务尽量 **纯读 parquet**（你当前生产环境若已热缓存，全池耗时应显著低于本次冷跑 8min）。  
3. **P2（可选）**：按 §4 做「日终特征一行」磁盘缓存；**仅在 P0/P1 仍不够时再动 `etf_rotation_core`**。

---

**状态**：试验已完成；**未修改** `etf_rotation_core` 生产路径。你确认优先级（先做 P0 重复拉取排查 vs 直接上 P2 特征缓存）后，再进入编码阶段。
