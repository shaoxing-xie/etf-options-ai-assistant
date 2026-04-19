---
name: ota_equity_factor_screening_brief
description: 解读 tool_screen_equity_factors / tool_finalize_screening_nightly：universe、因子、success/quality_score/degraded/config_hash、申万映射与熔断；与旧 tool_quantitative_screening 的迁移说明。
---

# OTA：`tool_screen_equity_factors` 多因子筛选口径

## 何时使用

- 调用或解释 **`tool_screen_equity_factors`**（主实现：`openclaw-data-china-stock` → `plugins/analysis/equity_factor_screening.py`，助手经 `plugins/analysis/equity_factor_screening.py` 动态加载）。
- 夜盘收尾、落盘与观察池：**`tool_finalize_screening_nightly`**（`src/screening_ops.py`），门禁见 `config/data_quality_policy.yaml` → `screening` 与 `src/screening_quality_gate.py`。
- 用户问「震荡选股」「A 股多因子」「申万行业动量」「观察池」。

## 与旧工具的差异（迁移）

| 旧 | 新 |
|----|-----|
| `tool_quantitative_screening`（`candidates`、**`status`** success/error） | **`tool_screen_equity_factors`**（**`success`** 布尔、`universe`、`factors`、`regime_hint`） |
| 动量/波动/流动性/估值四因子 | 默认 **`reversal_5d` / `fund_flow_3d` / `sector_momentum_5d`**（震荡模板权重在插件内） |
| 无统一质量分 | 返回 **`quality_score`**、**`config_hash`**、**`sw_mapping`**（申万映射覆盖率） |

旧规程 Skill **`ota_quantitative_screening_brief`** 已 **deprecated**，请改用本 Skill。

## 返回契约（要点）

- 成功：**`success`: true**，**`data`**: 列表，元素含 **`symbol` / `score` / `factors`**。
- 失败：**`success`: false**，**`message`**。
- 必看：**`quality_score`**、**`degraded`**、**`degraded_notes`**、**`elapsed_ms`**、**`plugin_version`**。

## 熔断与观察池

- **`config/weekly_calibration.json`**：`regime: pause` 时收尾工具跳过观察池写入。
- **`data/screening/emergency_pause.json`**：由 **`tool_set_screening_emergency_pause`** 或工作流 `screening_emergency_stop.yaml` 维护。
- 审计落盘：**`data/screening/YYYY-MM-DD.json`**（含完整 screening 副本与门禁结果）。

## 权威路径

- 插件：`openclaw-data-china-stock/plugins/analysis/equity_factor_screening.py`
- 助手收尾：`etf-options-ai-assistant/src/screening_ops.py`
- Manifest：`config/tools_manifest.yaml` → `tool_screen_equity_factors`、`tool_finalize_screening_nightly`
