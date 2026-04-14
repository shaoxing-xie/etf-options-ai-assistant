# 513880 尾盘监控实施方案（存档）

## 目标
- 新增交易日 14:40 定时任务，生成 `tail_session` 报告
- 验证并补齐关键缺口：
  - IOPV/折溢价多源稳定读取
  - 公告风险联动 (`risk_notice_rules`)
  - 新报告类型 `tail_session`
  - 参数化配置 (`gate_rules` / `option_profiles` / `risk_notice_rules`)
  - 执行摩擦约束（成交额代理流动性）

## 主要实现点
- 新增运行器：`plugins/notification/run_tail_session_analysis.py`
- 新增工作流：`workflows/tail_session_513880.yaml`
- 新工具映射：`tool_run_tail_session_analysis_and_send`
- 新报告分支：`send_daily_report.py` 中 `report_type=tail_session`
- 参数落地：`config/domains/analytics.yaml` 的 `nikkei_tail_session` 配置段

## 数据源与回退
- IOPV主源：push2 单票接口（单只ETF）
- IOPV备源：push2 全量列表
- 价格快照备源：THS/Sina（可能无 IOPV，仅降级输出）

## 验证建议
- 运行单测与编译检查，确认新增 runner/模板/配置可加载
- 在 test 模式跑一次 tail_session 工具，核对分层输出与风险提示
- 上线前至少完成一个交易日的 dry-run 日志核验
