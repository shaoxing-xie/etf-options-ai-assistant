---
name: ota_quantitative_screening_brief
description: "[DEPRECATED] 已由 ota_equity_factor_screening_brief + tool_screen_equity_factors 取代；以下为历史口径说明。"
---

> **Deprecated**：`tool_quantitative_screening` 已从 manifest 移除。请改用 **`skills/ota-equity-factor-screening-brief/SKILL.md`**（`ota_equity_factor_screening_brief`）与 **`tool_screen_equity_factors`**。

# OTA：`tool_quantitative_screening` 历史口径（归档）

以下内容仅用于对照旧会话；新工作流请勿引用。

## 何时使用（历史）

- 解释已归档的 **`tool_quantitative_screening`**（`plugins/analysis/quantitative_screening.py`）。
- 用户问「多因子排序」「候选 ETF/股票打分」「top_picks」且工具返回含 **`scores` / `ranked_list` / `top_picks`**。

## 返回契约（与多数分析工具的差异）

- 成功时 **`status`: `"success"`**，失败时 **`status`: `"error"`** 及 **`error`** 文案；**没有**统一的布尔字段 **`success`**（勿与 `tool_assess_risk` 等混读）。
- **`failed`**：按标的记录拉取或因子计算失败原因，便于说明「部分候选无分」。

## 因子与权重（实现默认值）

| 因子 | 含义（简） | 方向 |
|------|------------|------|
| momentum | 窗口内收盘涨幅 | 越大越好 |
| volatility | 日收益波动 | 越小越好（得分按反向归一） |
| liquidity | 平均成交额 | 越大越好 |
| valuation | 股票 PE_TTM（财务接口）；缺失时占位高 | 越低越好 |

默认合成权重（代码内）：动量 0.4、波动 0.2、流动性 0.3、估值 0.1。横截面在**有效样本**上做秩归一再加权。

## 参数要点

- **`candidates`**：列表或逗号/分号分隔字符串。
- **`lookback_days`**：日线回溯长度（默认 20）。
- **`universe`**：`etf` / `stock` / `None`（`None` 时按代码粗判 ETF vs 股票数据源）。

## 边界说明（避免过度承诺）

- **非**中性化、**非**完整 IC/IR 回测验证的机构选股引擎；适合 **助手内候选排序、研究报告附录、工作流前置筛池**。
- 与 **`tool_etf_rotation_research`** 区分：轮动工具侧重池配置与多维排名+研究摘要；本工具侧重**用户给定候选列表**的快速打分。

## 权威代码（归档）

- [`plugins/analysis/quantitative_screening.py`](../../plugins/analysis/quantitative_screening.py)（若仓库仍保留该文件）
