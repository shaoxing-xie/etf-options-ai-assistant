# 研究文档（`docs/research/`）

本目录存放**与策略/报告口径、预测试验、路线图**相关的研究说明，不等同于用户手册；实盘前请结合 `docs/openclaw/工作流参考手册.md` 与工具参考。

| 文档 | 内容 |
|------|------|
| [`prediction_fusion_contract.md`](prediction_fusion_contract.md) | 多模型波动区间融合离线试验契约（与 `scripts/prediction_fusion_experiment.py` 配套）。 |
| [`factor_research_checklist.md`](factor_research_checklist.md) | 因子研究 Checklist（与演化工作流、研究文档迭代配合）。 |
| [`daily_market_report_web_benchmark.md`](daily_market_report_web_benchmark.md) | 每日市场分析报告章节对标与质量基准（与 `workflows/daily_market_report.yaml`、钉钉日报对齐）。 |
| [`opening_morning_brief_roadmap.md`](opening_morning_brief_roadmap.md) | 开盘晨报/盘前链路能力路线图与落地项。 |

相关运行配置：根目录 `research.md`（若使用 OpenClaw 全局 prompts，路径以本机 `~/.openclaw/prompts/research.md` 为准）、`workflows/before_open_analysis.yaml`、`workflows/opening_analysis.yaml`。
