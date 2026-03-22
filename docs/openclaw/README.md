# OpenClaw 集成与配置

本目录面向负责 OpenClaw 环境、Gateway、Cron 工作流和插件部署的使用者。

> 文档状态说明：本目录含“历史积累 + 当前可用”内容。  
> 对外发布与稳定运行请优先使用 `docs/publish/` 下的主线文档（部署、环境变量、Ollama、服务启停、插件技能）。

主要内容包括：

- **当前可用（推荐）**  
  - `工作流参考手册.md`：各个工作流（盘前、盘后、盘中、研究模式一、策略评估等）的配置与调度。  
  - **策略引擎与信号融合**：工具 `tool_strategy_engine`；仓库定时 **`strategy_fusion`**（交易时段 **每 30 分钟**）；详见 `docs/architecture/strategy_engine_and_signal_fusion.md`、`config/openclaw_strategy_engine.yaml`、`workflows/strategy_fusion_routine.yaml`；本机 Cron 以 `~/.openclaw/cron/jobs.json` 为准。
  - `Strategy_Research_Loop.md`：策略研究闭环设计与相关工作流说明。
  - `ETF_Rotation_Research_Workflow.md`：ETF 轮动研究工作流的设计与调度建议。
  - `信号与风控巡检工作流.md`：巡检工作流与风控检查流程。

- **优化与成本控制**  
  - `OpenClaw工具与Token优化建议.md`：如何通过精简工具暴露、调整 Agent 工具权限来减少 token 消耗与运行成本。

- **历史归档（不纳入发布清单）**  
  - `docs/archive/openclaw/README.md`
  - `docs/archive/openclaw/OpenClaw配置指南.md`
  - `docs/archive/openclaw/插件集成到OpenClaw指南.md`
  - `docs/archive/openclaw/README_WSL_ACCESS.md`

如需对 Gateway / Cron / Agent 配置进行较大调整，建议先完整阅读本目录下的文档，再在测试环境中演练。
