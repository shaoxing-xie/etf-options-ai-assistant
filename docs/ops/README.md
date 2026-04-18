# Ops 运维与排错

本目录面向负责运维 OpenClaw + 本项目的使用者，涵盖：

- 常见问题与解决方案；
- 风险控制与回滚路径；
- 部分平台（钉钉 / 飞书等）的连接排查思路。

主要文档：

- `常见问题库.md`  
  - 按“数据 / 计算 / 网络 / 配置 / 安装 / 性能 / 日志与监控”等分类整理的 FAQ 列表。
- `RISK_CONTROL_AND_ROLLBACK.md`  
  - 当引入新的 Agent / 插件 / 工作流后，如何在出现问题时进行风险控制与快速回滚。
- `回测使用指导-自动任务与日常交互.md`
  - **`backtesting-trading-strategies`** 脚本回测在 Cron/Workflow 与 **钉钉/OpenClaw** 下的实操（**§5** 可复制话术与 `exec` 模板、`settings.yaml`、数据源、**§6** 故障、**§7** 脚本实测）；不含涨停回马枪专题工具说明。
- 其他运维相关清单与指南（例如需要添加交易日判断跳过参数的工具清单等）。
- [`cron_signal_inspection_triage.md`](cron_signal_inspection_triage.md) — **宽基 ETF 信号+风控巡检**（`workflows/signal_risk_inspection.yaml`）Cron 失败时的排查与分流（含钉钉 `310000` 加签、工具冒烟脚本索引）。

在出现异常行为（如工具持续失败、Cron 任务执行异常、Gateway 无法启动等）时，建议优先查阅本目录文档。

辅助脚本（Cron 冒烟、第三方技能检查、数据库索引等）说明见仓库根目录 **`scripts/README.md`**；测试与集成脚本见 **`tests/README.md`**。
