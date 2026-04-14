# User Guide 使用指南

本目录聚焦“如何在日常中使用本助手”，而不是工具参数细节或底层实现。当前项目主方向为 A股 / ETF 交易辅助，期权能力作为扩展能力保留。

推荐主题：

- **工作流与调度**  
  - `docs/openclaw/工作流参考手册.md`：盘前 / 盘后 / 开盘 / 盘中等工作流的整体设计和调度策略。
- **信号与风控巡检**  
  - `docs/openclaw/信号与风控巡检工作流.md`：工作流 A（信号 + 风控巡检）的端到端说明。
- **策略引擎与多路信号融合**  
  - `docs/architecture/strategy_engine_and_signal_fusion.md`：工具 `tool_strategy_engine`、Journal、与风控边界。  
  - 调度：仓库 `agents/analysis_agent.yaml` 的 **`strategy_fusion`**（交易时段 **每 30 分钟**）；OpenClaw 实操见 `docs/openclaw/工作流参考手册.md`「策略引擎与信号融合」、`config/openclaw_strategy_engine.yaml`。
- **通知与日报**  
  - 结合工具手册中的飞书/钉钉工具以及相应工作流配置文档；每日市场报告见 `workflows/daily_market_report.yaml` 与 `docs/research/daily_market_report_web_benchmark.md`。
- **研究与长文（research.md 驱动）**  
  - ETF 轮动：管道版 `workflows/etf_rotation_research.yaml`（`tool_etf_rotation_research` → `tool_send_analysis_report`）；标的池与因子默认来自 **`config/rotation_config.yaml`** 与 **`config/symbols.json`**；Agent 版 `workflows/etf_rotation_research_agent.yaml`；轮动回测工具 `tool_backtest_etf_rotation`。策略回放：`workflows/strategy_research_playback.yaml`。涨停回马枪盘后：`workflows/limitup_pullback_after_close.yaml`（索引见 `workflows/README.md`）。

在你已经完成 `docs/getting-started/` 中的快速开始后，建议从这里继续深入，逐步把工作流和信号/风控流程融入到自己的研究与盘中节奏中。
