# 插件集成到OpenClaw指南

> 状态：该文档为早期集成记录，包含较多 `/mnt/d/...` 路径示例。  
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
- ✅ 环境：Windows 11 + WSL2

### 2. 配置Windows和WSL文件系统互访

**重要**：配置Windows和WSL可以互访文件系统，避免文件复制。

#### 2.1 确认Windows路径在WSL中的映射

```bash
# 在WSL中测试Windows路径访问
# Windows D盘 -> WSL /mnt/d/
# Windows C盘 -> WSL /mnt/c/

# 测试您的项目路径
ls /mnt/d/Ubuntu应用环境配置/mcp/option_trading_assistant/etf-options-ai-assistant/plugins/

# 如果可访问，说明文件系统互访已配置好
```

#### 2.2 路径映射关系

| Windows路径 | WSL路径 |
|------------|---------|
| `D:\Ubuntu应用环境配置\mcp\` | `/mnt/d/Ubuntu应用环境配置/mcp/` |
| `D:\Ubuntu应用环境配置\mcp\option_trading_assistant\` | `/mnt/d/Ubuntu应用环境配置/mcp/option_trading_assistant/` |
| `D:\Ubuntu应用环境配置\mcp\option_trading_assistant\etf-options-ai-assistant\plugins\` | `/mnt/d/Ubuntu应用环境配置/mcp/option_trading_assistant/etf-options-ai-assistant/plugins/` |

#### 2.3 配置建议

**推荐方案**：使用符号链接，让OpenClaw插件直接访问Windows路径，无需复制文件。

### 3. 确认原系统API服务

**重要**：确保原系统的API服务正在运行：

```bash
# 在Windows中启动原系统API服务
# 原系统API地址：http://localhost:5000
# 启动命令（在Windows PowerShell中）：
cd D:\Ubuntu应用环境配置\mcp\option_trading_assistant
python main.py --api-only

# 或者在WSL中测试API连接
curl http://localhost:5000/api/status
```

**注意**：由于OpenClaw在WSL中，原系统API在Windows中，需要确保：
- ✅ Windows防火墙允许5000端口访问
- ✅ 或者使用 `127.0.0.1:5000` 而不是 `localhost:5000`

### 4. 确认插件代码位置

插件代码位于：
```
Windows: D:\Ubuntu应用环境配置\mcp\option_trading_assistant\etf-options-ai-assistant\plugins\
WSL:     /mnt/d/Ubuntu应用环境配置/mcp/option_trading_assistant/etf-options-ai-assistant/plugins/
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

## 🔧 第三步：配置文件系统互访（推荐方案）

### 方案A：使用符号链接（推荐，无需复制文件）

**优势**：
- ✅ 无需复制文件，节省磁盘空间
- ✅ 代码修改后立即生效，无需同步
- ✅ 保持单一数据源，避免版本不一致

**步骤**：

```bash
# 在WSL中执行
cd ~/.openclaw/extensions/option-trading-assistant

# 创建plugins目录（如果不存在）
mkdir -p plugins

# 创建符号链接到Windows路径
ln -s /mnt/d/Ubuntu应用环境配置/mcp/option_trading_assistant/etf-options-ai-assistant/plugins/* ./plugins/

# 或者逐个创建符号链接（更安全）
ln -s /mnt/d/Ubuntu应用环境配置/mcp/option_trading_assistant/etf-options-ai-assistant/plugins/data_collection ./plugins/data_collection
ln -s /mnt/d/Ubuntu应用环境配置/mcp/option_trading_assistant/etf-options-ai-assistant/plugins/analysis ./plugins/analysis
ln -s /mnt/d/Ubuntu应用环境配置/mcp/option_trading_assistant/etf-options-ai-assistant/plugins/notification ./plugins/notification
ln -s /mnt/d/Ubuntu应用环境配置/mcp/option_trading_assistant/etf-options-ai-assistant/plugins/data_access ./plugins/data_access
```

### 方案B：直接使用Windows路径（最简单）

**优势**：
- ✅ 最简单，无需任何配置
- ✅ 代码修改后立即生效

**步骤**：

在插件入口文件中直接使用Windows路径：

```python
# 在 index.py 中
import sys
import os

# 添加项目根目录到 Python 路径（与仓库内 `from plugins.data_collection...` 一致）
windows_project_root = "/mnt/d/Ubuntu应用环境配置/mcp/option_trading_assistant/etf-options-ai-assistant"
sys.path.insert(0, windows_project_root)

# 然后正常导入
from plugins.data_collection.index.fetch_realtime import tool_fetch_index_realtime
# ...
```

### 方案C：复制文件（传统方案）

如果符号链接有问题，可以复制文件：

```bash
# 在WSL中执行
cd ~/.openclaw/extensions/option-trading-assistant

# 复制插件目录
cp -r /mnt/d/Ubuntu应用环境配置/mcp/option_trading_assistant/etf-options-ai-assistant/plugins ./plugins

# 或者使用rsync（更高效，支持增量更新）
rsync -av /mnt/d/Ubuntu应用环境配置/mcp/option_trading_assistant/etf-options-ai-assistant/plugins/ ./plugins/
```

### 3.2 验证文件访问

```bash
# 检查Windows路径是否可访问
ls -la /mnt/d/Ubuntu应用环境配置/mcp/option_trading_assistant/etf-options-ai-assistant/plugins/

# 检查符号链接（如果使用方案A）
ls -la ~/.openclaw/extensions/option-trading-assistant/plugins/

# 应该看到：
# data_collection -> /mnt/d/.../plugins/data_collection
# analysis -> /mnt/d/.../plugins/analysis
# notification -> /mnt/d/.../plugins/notification
# data_access -> /mnt/d/.../plugins/data_access
```

### 3.3 配置WSL访问Windows文件系统

**确保WSL可以访问Windows文件系统**：

```bash
# 在WSL中测试Windows路径访问
# D盘路径：/mnt/d/
# C盘路径：/mnt/c/

# 测试访问
ls /mnt/d/Ubuntu应用环境配置/mcp/

# 如果无法访问，检查WSL配置
# 在Windows PowerShell中执行：
wsl --list --verbose
```

**注意事项**：
- ⚠️ Windows路径中的中文字符在WSL中可能需要UTF-8编码
- ⚠️ 文件权限：Windows文件在WSL中可能显示为 `drwxrwxrwx`（所有权限）
- ⚠️ 性能：直接访问Windows文件系统可能比WSL原生文件系统稍慢
- ✅ 建议：使用符号链接（方案A），兼顾性能和便利性

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
from plugins.analysis.signal_generation import tool_generate_signals
from plugins.analysis.risk_assessment import tool_assess_risk
from plugins.analysis.intraday_range import tool_predict_intraday_range

# 导入通知工具
from plugins.notification.send_feishu_message import tool_send_feishu_message
from plugins.notification.send_signal_alert import tool_send_signal_alert
from plugins.notification.send_daily_report import tool_send_daily_report
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

# 导出所有工具函数
__all__ = [
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
    'tool_generate_signals',
    'tool_assess_risk',
    'tool_predict_intraday_range',
    # 通知工具
    'tool_send_feishu_message',
    'tool_send_signal_alert',
    'tool_send_daily_report',
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
    "tool_generate_signals",
    "tool_assess_risk",
    "tool_predict_intraday_range",
    "tool_send_feishu_message",
    "tool_send_signal_alert",
    "tool_send_daily_report",
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
- 原系统API服务未运行
- 网络连接问题
- API地址配置错误

**解决方法**：
```bash
# 测试API连接
curl http://localhost:5000/api/status

# 如果失败，检查原系统服务
# 在Windows中启动：python main.py --api-only
```

---

## 📋 第九步：验证工具功能

### 9.1 测试单个工具

在OpenClaw Dashboard或通过命令行测试：

```bash
# 测试交易状态检查工具
openclaw tool call tool_check_trading_status

# 测试指数实时数据工具
openclaw tool call tool_fetch_index_realtime --index_code "000300"
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
3. 测试API连接：确保原系统API服务正常运行
4. 参考OpenClaw文档：https://docs.openclaw.ai

---

**最后更新**：2026-02-16
