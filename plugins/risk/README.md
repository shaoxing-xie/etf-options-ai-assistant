# 风控插件（`plugins/risk/`）

本目录提供**组合与机构向风控辅助工具**：读本地 JSON/YAML 配置 + ETF 日线缓存，输出可嵌入巡检报告的结构化结论。与单标的风险评估（`plugins/analysis/risk_assessment.py` → **`tool_assess_risk`**：ETF/指数/A 股、HV 与合并后配置 → `risk_assessment`（域文件：`config/domains/risk_quality.yaml`））**互补**（组合用本目录工具，单标的用 `tool_assess_risk`）。

## 模块与工具

| 模块 | `tool_*` | 说明 |
|------|-----------|------|
| `portfolio_risk_snapshot.py` | `tool_portfolio_risk_snapshot` | 基于 `config/portfolio_weights.json`（或 `*.example.json`）与 `config/risk_thresholds.yaml`，结合 ETF 日线缓存计算历史模拟 VaR、最大/当前回撤、仓位相对阈值标志。 |
| `institutional_risk.py` | `tool_compliance_rules_check`、`tool_stop_loss_lines_check`、`tool_stress_test_linear_scenarios`、`tool_risk_attribution_stub` | 合规规则展示、止损线配置读取、线性压力情景（占位实现以配置为准）、风险归因占位。 |

## 配置（仓库内）

- `config/portfolio_weights.json` / `config/portfolio_weights.example.json`：组合权重与现金比例 schema。  
- `config/risk_thresholds.yaml` / `config/risk_thresholds.example.yaml`：VaR 置信度、回撤与仓位告警阈值。  
- `config/compliance_rules.example.yaml`、`config/stop_loss_lines.example.yaml`：合规与止损线示例（按需复制为无 `.example` 文件名并本地填写）。

## 典型衔接

- 工作流 **`workflows/signal_risk_inspection.yaml`**：宽基 ETF 巡检快报第四节调用 `tool_portfolio_risk_snapshot`。  
- 运维排错：[`docs/ops/cron_signal_inspection_triage.md`](../../docs/ops/cron_signal_inspection_triage.md)。

## 依赖

- 数值：`numpy`（VaR/回撤计算）。  
- 可选：`pyyaml`（读阈值 YAML）。
