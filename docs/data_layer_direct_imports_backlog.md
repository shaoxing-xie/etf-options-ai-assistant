# 直连行情库引用 backlog（Phase 3 扫描快照）

**推荐（可复现、与 CI 一致）**：

```bash
python scripts/scan_direct_connections.py
python scripts/scan_direct_connections.py --summary-only
```

**可选**：本机已安装 [ripgrep](https://github.com/BurntSushi/ripgrep) 时，亦可用手工一行（与上表口径略宽/略窄时以脚本为准）：

```bash
rg "import akshare|from akshare|import tushare|from tushare" --type py . \
  -g '!*.recovery_backups/*' -g '!**/.venv/**'
```

**当前快照（助手仓）**

| 模块 | 分类建议 |
|------|----------|
| `src/data_collector.py` | 采集主路径：日线已插件优先；分钟/期权/A50 等仍含直连，逐个迁移 `tool_fetch_*` |
| `src/tushare_fallback.py` | Tushare 兜底 |
| `src/trend_analyzer.py` | Spot/全市场行情语义 |
| `src/market_calibrator/market_data_fetcher.py` | 校准用采集 |
| `src/underlying_resolver.py` | 名称解析 |
| `src/config_loader.py` | 交易日历工具导入 |
| `src/features/six_index_features.py` | 特征兜底 |
| `tests/manual/manual_index_opening_apis.py` | 手工脚本，非 CI |
