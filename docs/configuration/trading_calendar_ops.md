# 交易日历运维

## Q4 检查项

在每年 **第四季度** 确认 `config/reference/holidays_*.yaml` 已包含 **次年** 文件（例如 `holidays_2027.yaml`），避免元旦后仍按错误交易日历运行。

## 文件加载口径

- 运行时通过 `system.trading_hours.calendar_source: files` + `calendar_path_glob` 自动加载年度文件。
- 主配置仅保留加载方式；年度节假日列表不再内联在 `config/environments/base.yaml`。
- 单文件格式支持：
  - `["20260101", ...]`
  - `{2026: ["20260101", ...]}`

## 与校验脚本

`scripts/validate_config_cross.py` 在缺少「当前年+1」年份键时会输出提醒（不单独阻塞 CI，除非团队将脚本设为硬门禁）。
