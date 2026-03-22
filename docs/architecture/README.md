# Architecture 架构与开发

本目录面向希望阅读、修改或扩展本项目的开发者。

主要文档：

- `PROJECT_LAYOUT.md`  
  - 描述项目根目录与各子目录的职责划分（`src/`、`plugins/`、`workflows/`、`docs/` 等）。
  - 解释原系统与 OpenClaw 插件层之间的边界（`tool_runner.py` 如何桥接）。

- `架构与工具审查报告.md`  
  - 从“易维护性 / 可观测性 / Token 成本 / 工具设计”等角度，对当前实现做的系统性审查与建议。

- `strategy_engine_and_signal_fusion.md`  
  - 策略引擎与信号融合 v1.0：`SignalCandidate` 契约、`tool_strategy_engine`、与 `strategy_config` / Journal 的边界；**OpenClaw / `~/.openclaw` Cron 与每 30 分钟 `strategy_fusion` 约定**见该文档「OpenClaw 与本机 Cron」节。  
  - 配套：`config/openclaw_strategy_engine.yaml`、`config/strategy_fusion.yaml`、`plugins/strategy_engine/README.md`。

建议阅读顺序：

1. `PROJECT_LAYOUT.md`：先理解整体版图与模块划分；
2. `架构与工具审查报告.md`：再结合具体代码与插件实现，评估哪些优化建议值得落地；
3. 若扩展多策略融合：阅读 `strategy_engine_and_signal_fusion.md`。

在做较大规模的重构或功能扩展前，建议先阅读本目录文档。
