# Agent 配置

本目录包含 OpenClaw Agent 配置文件。

## Agent 列表

1. **data_collector_agent.yaml** - 数据采集 Agent
2. **analysis_agent.yaml** - 分析 Agent
3. **scheduler_agent.yaml** - 调度 Agent

## 配置说明

这些配置文件需要根据 OpenClaw 的实际格式进行调整。
请参考 OpenClaw 官方文档进行配置。

## 定时任务配置

- 盘后分析：15:30（工作日）
- 盘前分析：9:15（工作日）
- 开盘分析：9:28（工作日）
- 日内波动区间：每30分钟（交易时间内）
- 信号生成：每5分钟（交易时间内）
- 数据采集：9:30, 10:00, 11:00, 13:00, 14:00, 15:00
