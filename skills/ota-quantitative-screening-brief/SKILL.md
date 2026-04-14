---
name: ota_quantitative_screening_brief
description: 解读 tool_quantitative_screening：候选池、动量/波动/流动性/估值因子、固定权重合成、status 字段（success/error）；非机构因子库，输出仅供排序与候选筛选。
---

# OTA：`tool_quantitative_screening` 量化筛选口径

## 何时使用

- 调用或解释 **`tool_quantitative_screening`**（`plugins/analysis/quantitative_screening.py`）。
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

## 权威文档与代码

- [`plugins/analysis/README.md`](../../plugins/analysis/README.md)「其他 analysis 模块」表
- [`plugins/analysis/quantitative_screening.py`](../../plugins/analysis/quantitative_screening.py)
- [`config/tools_manifest.yaml`](../../config/tools_manifest.yaml)（`tool_quantitative_screening`）
