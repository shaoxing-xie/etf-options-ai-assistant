# 插件集成到OpenClaw指南

> 状态：该文档为早期集成记录，已更新为主线 WSL2 适用内容（不再依赖旧版兼容 API）。  
> 当前发布与生产部署请优先参考：
> - `docs/publish/deployment-openclaw.md`
> - `docs/publish/plugins-and-skills.md`
> - `docs/publish/service-ops.md`

**版本**: v1.0  
**创建日期**: 2026-02-16  
**适用环境**: WSL + OpenClaw 2026.2.15

---

## 📋 准备工作

### 1. 确认OpenClaw环境

根据您的状态信息，OpenClaw环境已部署：
- ✅ OpenClaw版本：2026.2.15
- ✅ Gateway运行中：http://127.0.0.1:18789
- ✅ 已注册插件：option_trader, feishu相关插件
- ✅ 环境：WSL2 + Ubuntu（OpenClaw 主线部署）

### 2. 主线部署建议（无需路径互访）

当前主线部署为 **完全基于 WSL + Ubuntu**，通常 **无需依赖旧版兼容 API**。

推荐直接在项目根目录执行主线安装脚本（会把插件安装到 `~/.openclaw/extensions/option-trading-assistant`，并创建必要的符号链接）：

```bash
cd /home/xie/etf-options-ai-assistant
bash install_plugin.sh
```

安装完成后重启并验收（见 `docs/publish/service-ops.md`）：

```bash
set -a; source ~/.openclaw/.env; set +a
~/scripts/restart-openclaw-services.sh
```

### 3. 确认插件代码位置

插件源代码位于（WSL 环境）：
```
/home/xie/etf-options-ai-assistant/plugins/
```

---

## 🚀 第一步：了解OpenClaw插件结构

### OpenClaw插件目录

OpenClaw插件通常位于：
```
~/.openclaw/extensions/  # 扩展插件目录
~/.openclaw/workspace/   # 工作区插件目录（根据配置）
```

### 插件格式要求

根据现有插件代码，OpenClaw插件需要：
1. **工具函数命名**：`tool_xxx()` 格式
2. **返回格式**：返回 `Dict[str, Any]` 格式
3. **错误处理**：包含完整的错误处理逻辑

### 工具与叙事分工（与 `llm_enhancer` 解耦）

- 分析类工具（如 `tool_predict_volatility`、趋势分析工具）**默认只返回结构化事实**（表格/Markdown/JSON 字段）；进程内不再调用 `src.llm_enhancer`（见合并后配置 → `llm_enhancer.enabled: false`，域文件：`config/domains/platform.yaml`）。
- 自然语言解读由 **Gateway 会话中的主模型**完成；约束见仓库 `skills/ota_openclaw_tool_narration`、`ota_volatility_prediction_narration`、`ota_signal_watch_narration` 等，并与 `config/snippets/openclaw_agents_ota_skills.json` 勾选对齐。
- **回滚**：将 `llm_enhancer.enabled` 设为 `true`，并从 git 历史恢复各处的 `enhance_with_llm` 调用；`Prompt_config.yaml` 保留为 legacy 模板参考。

### 趋势分析三工具（`tool_analyze_*`）

- **实现**：[`plugins/analysis/trend_analysis.py`](../../plugins/analysis/trend_analysis.py)；核心逻辑 [`src/trend_analyzer.py`](../../src/trend_analyzer.py)；落盘 [`src/data_storage.py`](../../src/data_storage.py)（`after_close` / `before_open` / **`opening_market` 分目录**）。
- **配置**：合并后配置顶层 **`trend_analysis_plugin`**（overlay、fallback；域文件：`config/domains/analytics.yaml`）；**`system.data_storage.trend_analysis.opening_dir`**（域文件：`config/domains/platform.yaml`）。
- **结构化字段**：各模式 `data` 内均有 **`report_meta`**；**仅盘后**附加 **`daily_report_overlay`**（北向、全球现货、关键位、板块、可选 ADX）。叙事口径见仓库 Skill **`ota_trend_analysis_brief`**（`skills/ota-trend-analysis-brief/SKILL.md`），同步后执行 `bash scripts/sync_repo_skills_to_openclaw.sh`。
- **盘前**：隔夜 **A50 / 金龙（HXC）仅 `analyze_market_before_open` 使用**；未传盘后结果时**优先读落盘** `after_close`，见返回 **`after_close_basis`**（`disk` / `computed` / `passed`）。
- **冒烟**：`python scripts/smoke_trend_analysis.py`（见 [`scripts/README.md`](../../scripts/README.md)）。

---

## 📦 第二步：创建OpenClaw插件目录结构

### 方案A：作为扩展插件（推荐）

```bash
# 在WSL中执行
cd ~/.openclaw/extensions

# 创建插件目录
mkdir -p option-trading-assistant/plugins
```

### 方案B：作为工作区插件

```bash
# 在WSL中执行
cd ~/.openclaw/workspace

# 创建插件目录
mkdir -p plugins
```

**建议**：使用方案A（扩展插件），便于管理和更新。

---

## 🔧 第三步：主线安装与验证（WSL2）

不建议再进行路径互访配置。当前主线部署推荐直接使用仓库提供的安装脚本：

```bash
cd /home/xie/etf-options-ai-assistant
bash install_plugin.sh
```

安装完成后，验证 OpenClaw 扩展目录下的插件结构是否正常：

```bash
cd ~/.openclaw/extensions/option-trading-assistant
ls -la
ls -la plugins
```

如结构异常，请回到 `docs/publish/deployment-openclaw.md` 按主线流程复验。

---

## 📝 第四步：创建插件入口文件

### 4.1 创建主插件文件

在 `~/.openclaw/extensions/option-trading-assistant/` 目录下创建 `index.py`：

```python
"""
期权交易助手插件
OpenClaw插件入口文件
"""

from typing import Dict, Any, List
import sys
import os

# 将扩展目录作为项目根加入路径（该目录下应有 plugins/data_collection、plugins/analysis 等）
plugin_dir = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, plugin_dir)

# 导入数据采集工具（与仓库内一致：项目根 + from plugins.data_collection...）
from plugins.data_collection.index.fetch_realtime import tool_fetch_index_realtime
from plugins.data_collection.index.fetch_historical import tool_fetch_index_historical
from plugins.data_collection.index.fetch_minute import tool_fetch_index_minute
from plugins.data_collection.index.fetch_opening import tool_fetch_index_opening
from plugins.data_collection.index.fetch_global import tool_fetch_global_index_spot

from plugins.data_collection.etf.fetch_realtime import tool_fetch_etf_realtime
from plugins.data_collection.etf.fetch_realtime import tool_fetch_etf_iopv_snapshot
from plugins.data_collection.etf.fetch_historical import tool_fetch_etf_historical
from plugins.data_collection.etf.fetch_minute import tool_fetch_etf_minute

from plugins.data_collection.option.fetch_realtime import tool_fetch_option_realtime
from plugins.data_collection.option.fetch_greeks import tool_fetch_option_greeks
from plugins.data_collection.option.fetch_minute import tool_fetch_option_minute

from plugins.data_collection.futures.fetch_a50 import tool_fetch_a50_data

from plugins.data_collection.utils.get_contracts import tool_get_option_contracts
from plugins.data_collection.utils.check_trading_status import tool_check_trading_status

# 导入分析工具
from plugins.analysis.technical_indicators import tool_calculate_technical_indicators
from plugins.analysis.trend_analysis import (
    tool_analyze_after_close,
    tool_analyze_before_open,
    tool_analyze_opening_market
)
from plugins.analysis.volatility_prediction import tool_predict_volatility
from plugins.analysis.historical_volatility import tool_calculate_historical_volatility
from plugins.analysis.underlying_historical_snapshot import (
    tool_underlying_historical_snapshot,
    tool_historical_snapshot,
)
from plugins.analysis.signal_generation import (
    tool_generate_option_trading_signals,
    tool_generate_signals,  # 期权信号兼容别名
)
from plugins.analysis.risk_assessment import tool_assess_risk
from plugins.analysis.intraday_range import tool_predict_intraday_range

# 导入通知工具
from plugins.notification.send_feishu_message import tool_send_feishu_message
from plugins.notification.send_signal_alert import tool_send_signal_alert
from plugins.notification.send_daily_report import tool_send_daily_report
from plugins.notification.send_analysis_report import tool_send_analysis_report
from plugins.notification.send_risk_alert import tool_send_risk_alert

# 导入数据访问工具
from plugins.data_access.read_cache_data import (
    tool_read_index_daily,
    tool_read_index_minute,
    tool_read_etf_daily,
    tool_read_etf_minute,
    tool_read_option_minute,
    tool_read_option_greeks
)

# 合并入口（与 config/tools_manifest.yaml / tool_runner.py 一致，OpenClaw 侧优先暴露）
from plugins.merged.fetch_index_data import tool_fetch_index_data
from plugins.merged.fetch_etf_data import tool_fetch_etf_data
from plugins.merged.fetch_option_data import tool_fetch_option_data
from plugins.merged.read_market_data import tool_read_market_data
from plugins.data_collection.sector import tool_fetch_sector_data

# 导出所有工具函数
__all__ = [
    # 数据采集 - 合并入口（推荐）
    'tool_fetch_index_data',
    'tool_fetch_etf_data',
    'tool_fetch_option_data',
    'tool_read_market_data',
    'tool_fetch_sector_data',
    # 数据采集 - 指数
    'tool_fetch_index_realtime',
    'tool_fetch_index_historical',
    'tool_fetch_index_minute',
    'tool_fetch_index_opening',
    'tool_fetch_global_index_spot',
    # 数据采集 - ETF
    'tool_fetch_etf_realtime',
    'tool_fetch_etf_historical',
    'tool_fetch_etf_minute',
    # 数据采集 - 期权
    'tool_fetch_option_realtime',
    'tool_fetch_option_greeks',
    'tool_fetch_option_minute',
    # 数据采集 - 期货
    'tool_fetch_a50_data',
    # 数据采集 - 工具
    'tool_get_option_contracts',
    'tool_check_trading_status',
    # 分析工具
    'tool_calculate_technical_indicators',
    'tool_analyze_after_close',
    'tool_analyze_before_open',
    'tool_analyze_opening_market',
    'tool_predict_volatility',
    'tool_calculate_historical_volatility',
    'tool_underlying_historical_snapshot',
    'tool_historical_snapshot',
    'tool_generate_option_trading_signals',
    'tool_generate_signals',
    'tool_assess_risk',
    'tool_predict_intraday_range',
    # 通知工具
    'tool_send_feishu_message',
    'tool_send_signal_alert',
    'tool_send_daily_report',
    'tool_send_analysis_report',
    'tool_send_risk_alert',
    # 数据访问工具
    'tool_read_index_daily',
    'tool_read_index_minute',
    'tool_read_etf_daily',
    'tool_read_etf_minute',
    'tool_read_option_minute',
    'tool_read_option_greeks',
]
```

### 4.2 创建插件配置文件

创建 `package.json` 或 `plugin.json`（根据OpenClaw要求）：

```json
{
  "name": "option-trading-assistant",
  "version": "1.0.0",
  "description": "期权交易助手插件 - 数据采集、分析、通知工具",
  "main": "index.py",
  "tools": [
    "tool_fetch_index_data",
    "tool_fetch_etf_data",
    "tool_fetch_option_data",
    "tool_read_market_data",
    "tool_fetch_sector_data",
    "tool_fetch_index_realtime",
    "tool_fetch_index_historical",
    "tool_fetch_index_minute",
    "tool_fetch_index_opening",
    "tool_fetch_global_index_spot",
    "tool_fetch_etf_realtime",
    "tool_fetch_etf_historical",
    "tool_fetch_etf_minute",
    "tool_fetch_option_realtime",
    "tool_fetch_option_greeks",
    "tool_fetch_option_minute",
    "tool_fetch_a50_data",
    "tool_get_option_contracts",
    "tool_check_trading_status",
    "tool_calculate_technical_indicators",
    "tool_analyze_after_close",
    "tool_analyze_before_open",
    "tool_analyze_opening_market",
    "tool_predict_volatility",
    "tool_calculate_historical_volatility",
    "tool_underlying_historical_snapshot",
    "tool_historical_snapshot",
    "tool_generate_option_trading_signals",
    "tool_generate_signals",
    "tool_assess_risk",
    "tool_predict_intraday_range",
    "tool_send_feishu_message",
    "tool_send_signal_alert",
    "tool_send_daily_report",
    "tool_send_analysis_report",
    "tool_send_risk_alert",
    "tool_read_index_daily",
    "tool_read_index_minute",
    "tool_read_etf_daily",
    "tool_read_etf_minute",
    "tool_read_option_minute",
    "tool_read_option_greeks"
  ]
}
```

---

## 🔍 第五步：检查OpenClaw插件格式要求

### 5.1 查看OpenClaw文档

```bash
# 查看OpenClaw插件文档
openclaw docs plugins

# 或访问在线文档
# https://docs.openclaw.ai/plugins
```

### 5.2 参考现有插件

查看已注册的插件格式：

```bash
# 查看option_trader插件结构（如果可见）
ls -la ~/.openclaw/extensions/option-trader/

# 或查看其他插件
ls -la ~/.openclaw/extensions/
```

---

## ⚙️ 第六步：配置OpenClaw识别插件

### 6.1 检查OpenClaw配置

```bash
# 查看OpenClaw配置
cat ~/.openclaw/openclaw.json
```

### 6.2 配置插件允许列表（如果需要）

如果OpenClaw要求配置插件允许列表，编辑配置文件：

```json
{
  "plugins": {
    "allow": [
      "option-trader",
      "option-trading-assistant"
    ]
  }
}
```

---

## 🧪 第七步：测试插件注册

### 7.1 重启OpenClaw Gateway

```bash
# 重启Gateway服务
sudo systemctl restart openclaw-gateway

# 或
openclaw gateway restart
```

### 7.2 检查插件是否注册

```bash
# 查看OpenClaw状态
openclaw status

# 应该看到新插件注册信息：
# [plugins] option-trading-assistant: Registered xxx tools
```

### 7.3 查看详细日志

```bash
# 查看OpenClaw日志
openclaw logs --follow

# 查找插件注册信息
```

---

## 🐛 第八步：故障排查

### 常见问题

#### 1. 插件未注册

**可能原因**：
- 插件目录位置不正确
- 插件入口文件格式不正确
- 工具函数命名不符合要求

**解决方法**：
```bash
# 检查插件目录
ls -la ~/.openclaw/extensions/option-trading-assistant/

# 检查入口文件
cat ~/.openclaw/extensions/option-trading-assistant/index.py

# 检查工具函数
grep -r "def tool_" ~/.openclaw/extensions/option-trading-assistant/
```

#### 2. 导入错误

**可能原因**：
- Python路径问题
- 依赖包未安装

**解决方法**：
```bash
# 安装依赖
pip install akshare pandas numpy requests

# 检查Python路径
python3 -c "import sys; print(sys.path)"
```

#### 3. API连接失败

**可能原因**：
- 若你使用的是当前主线流程，通常 **不需要** 兼容 API。
- 若你确实在插件配置里启用了 `apiBaseUrl`，则需确保该服务在 **当前环境（WSL/容器）** 已启动。
- 网络连接问题
- API地址配置错误

**解决方法**：
```bash
# 若你启用了兼容 API，则在与服务相同的环境中测试连通性
curl "<apiBaseUrl>/api/status"
```

---

## 📋 第九步：验证工具功能

### 9.1 测试单个工具

**说明**：OpenClaw CLI **没有** `openclaw tool` 子命令（2026.3.x 为 `unknown command 'tool'`）。验证插件工具请用下面两种方式之一。

**方式 A：与 Gateway 相同实现路径——在项目根用 `tool_runner.py`（推荐）**

```bash
cd ~/etf-options-ai-assistant   # 或你的克隆路径
.venv/bin/python tool_runner.py tool_check_trading_status '{}'
.venv/bin/python tool_runner.py tool_fetch_index_realtime '{"index_code":"000300"}'
# 技术指标（默认 standard，依赖 pandas-ta；可与 legacy 对比）
.venv/bin/python tool_runner.py tool_calculate_technical_indicators '{"symbol":"510300","data_type":"etf_daily","lookback_days":120}'
```

**`tool_calculate_technical_indicators` 说明（摘要）**：默认使用 **`pandas_ta`** 向量化（`engine=standard`）；`engine=legacy` 与旧版数值一致。指标名 **`indicators`** 须为小写（如 `ma`、`macd`、`rsi`、`bollinger`，及可选 `kdj`、`cci`、`adx`、`atr`）。周期与默认指标列表在 **合并后配置 → `technical_indicators`**（域文件：`config/domains/analytics.yaml`）。详见 `plugins/analysis/README.md` 与 Skill **`ota_technical_indicators_brief`**。

**钉钉自定义机器人（SEC 加签）环境变量**：
如果要调用 `tool_send_dingtalk_message` / `tool_send_analysis_report`，需要在 `~/.openclaw/.env` 配好：
- `OPENCLAW_DINGTALK_CUSTOM_ROBOT_WEBHOOK_URL`：自定义机器人 webhook（包含 `access_token`）
- `OPENCLAW_DINGTALK_CUSTOM_ROBOT_SECRET`：SEC 安全模式密钥（`SEC...`）
- `DINGTALK_KEYWORD`（或 `MONITOR_DINGTALK_KEYWORD`）：机器人“关键词安全校验”用

建议测试时使用 `mode="test"`（不发网络请求，只做参数校验），避免调试阶段触发 webhook 限流或签名窗口问题。

**方式 B：让已配置工具的 Agent 代为调用**

```bash
openclaw agent --agent etf_data_collector_agent --message "请只调用一次 tool_check_trading_status，并把返回 JSON 摘要给我" --json
```

（将 `etf_data_collector_agent` 换成你 `openclaw.json` / agents 里实际的数据采集 Agent `id`。）

**插件与网关健康（非单工具调用）**

```bash
openclaw plugins doctor
openclaw gateway probe
openclaw health
```

### 9.2 在Agent中使用

配置Agent使用新工具：

```yaml
# ~/.openclaw/agents/main/config.yaml
tools:
  - tool_check_trading_status
  - tool_fetch_index_realtime
  - tool_calculate_technical_indicators
  # ... 其他工具
```

---

## ✅ 完成检查清单

- [ ] 插件文件已复制到OpenClaw扩展目录
- [ ] 插件入口文件已创建
- [ ] 插件配置文件已创建
- [ ] OpenClaw配置已更新（如需要）
- [ ] Gateway服务已重启
- [ ] 插件已成功注册（在`openclaw status`中可见）
- [ ] 工具函数可以正常调用
- [ ] API连接正常
- [ ] 依赖包已安装

---

## 🎯 下一步

完成插件集成后，下一步是：

1. **配置Agent使用新工具**
2. **创建工作流使用新工具**
3. **测试端到端流程**
4. **优化和调试**

---

## 📞 需要帮助？

如果在集成过程中遇到问题：

1. 查看OpenClaw日志：`openclaw logs --follow`
2. 检查插件代码：确保所有工具函数都正确导出
3. 测试API连接：若启用了兼容 API，则确保 `apiBaseUrl` 对应的服务在当前环境可用
4. 参考OpenClaw文档：https://docs.openclaw.ai

---

**最后更新**：2026-02-16
