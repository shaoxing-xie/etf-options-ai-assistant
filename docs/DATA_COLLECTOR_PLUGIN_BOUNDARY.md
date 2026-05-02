# `data_collector` 与采集插件边界（P4）

## 原则

- **真源**：行情采集实现以 **`openclaw-data-china-stock`**（开发目录）为准；助手 `src/data_collector.py` 为 **编排 + 助手特有路径**（期权分钟、部分 spacing），**禁止**长期复制插件 `fetch_*` 多源链。
- **读缓存**：生产主路径应 **`tool_read_market_data` / `read_cache_data`**；默认 **不在线补拉**（`skip_online_refill=True`），需补拉时显式传 `False`。
- **统一工具**：Gateway / cron 应优先 **`tool_runner`** 登记工具，而非助手进程内直连东财/新浪 SDK（规划 §4.1.5）。

## 待收敛项（技术债登记）

- 助手与插件 **同名函数非逐行一致** 清单：以 PR 为单位对齐或改为仅调用 `plugins.data_collection.*`。
- `tushare_fallback` 迁移至插件 `connectors/tushare` 后，助手侧仅保留 **Token/permission_profile** 与调用封装。
