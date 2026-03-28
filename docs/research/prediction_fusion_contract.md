# 多模型预测融合 — 数据契约（离线试验用）

> 与 `tool_strategy_engine` 的信号融合无关；仅针对 **价格区间预测**（upper/lower）的实验与后续产品化前置设计。

## 输入：预测列表

每条记录至少包含：

| 字段 | 类型 | 说明 |
|------|------|------|
| `source` | string | 模型或链路标识，如 `minute_multi_period`、`fallback_daily`、`llm_aux` |
| `symbol` | string | 标的，如 `510300` |
| `upper` | number | 预测上轨（已统一到可比对单位，建议先经 `record_prediction` 同源标准化） |
| `lower` | number | 预测下轨 |
| `current_price` | number | 融合时刻的现价（用于宽度/门禁，可选） |
| `weight` | number | 非负权重；缺省为 1。生产态可由历史命中率映射而来 |
| `timestamp` | string | ISO 时间，可选 |

## 输出：融合区间

试验脚本输出：

- `fused_lower` / `fused_upper`：加权分位数（默认下 20%、上 80%）或简单加权中点±半宽
- `sources_used`：参与融合的来源列表
- `dropped`：被 2σ（按 midpoint）剔除的条目（若有）

## 生产前置条件（检查清单）

1. 各 `source` 的预测已 **同标的、同刻度**（元/指数点已统一）。
2. `weight` 与 **verify 命中统计** 同源更新，避免用单次会话口头准确率。
3. 融合结果若落库，须再走 **`prediction_quality` 门禁**（`config.yaml`）。

## 参考实现

`scripts/prediction_fusion_experiment.py`（仅 CLI / 离线，不接入定时任务）。
