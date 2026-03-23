# 通知插件

本目录包含宽基ETF及其期权交易助手的通知相关插件，融合了 Coze 插件的核心逻辑。

## 插件列表

### 1. send_feishu_message.py - 飞书消息通知

**功能说明**：
- 发送文本、富文本或卡片消息到飞书
- 融合 Coze `send_feishu_message.py` 的完整逻辑
- 支持 Webhook 和 API 两种方式
- 支持多种消息类型

**使用方法**：
```python
from plugins.notification.send_feishu_message import tool_send_feishu_message

# 发送文本消息
result = tool_send_feishu_message(
    message_type="text",
    content="交易信号：买入 510300，信号强度 0.75",
    webhook_url="https://open.feishu.cn/open-apis/bot/v2/hook/xxx"  # 可选
)

# 发送富文本消息
result = tool_send_feishu_message(
    message_type="rich_text",
    content="## 交易信号\n\n**标的**: 510300\n**信号**: 买入\n**强度**: 0.75"
)

# 发送卡片消息
result = tool_send_feishu_message(
    message_type="card",
    content={
        "header": {"title": {"tag": "plain_text", "content": "交易信号"}},
        "elements": [
            {"tag": "div", "text": {"tag": "plain_text", "content": "买入 510300"}}
        ]
    }
)
```

**输入参数**：
- `message_type` (str): 消息类型，可选值：
  - `"text"`: 文本消息
  - `"rich_text"`: 富文本消息（Markdown格式）
  - `"card"`: 卡片消息（交互式卡片）
- `content` (str/dict): 消息内容
  - 文本消息：字符串
  - 富文本消息：字符串（Markdown格式）或字典
  - 卡片消息：字典（卡片结构）
- `receiver_id` (str, optional): 接收者ID（用户ID或群聊ID，使用API时必填）
- `receiver_type` (str): 接收者类型，可选 "user" 或 "chat"，默认 "chat"
- `webhook_url` (str, optional): Webhook URL（优先使用）

**输出格式**：
```python
{
    "success": True,
    "message": "消息发送成功",
    "timestamp": "2025-01-15 14:30:00",
    "message_id": "om_xxx"  # 使用API时返回消息ID
}
```

**技术实现要点**：
- **Webhook 方式**（推荐）：
  - 使用飞书机器人 Webhook URL
  - 支持文本、富文本、卡片消息
  - 无需认证，配置简单
- **API 方式**：
  - 使用飞书开放平台 API
  - 需要 app_id 和 app_secret
  - 支持发送给指定用户或群聊
  - 需要 receiver_id
- **配置优先级**（支持多种配置方式）：
  1. **参数传入**：工具调用时直接传入配置（最高优先级）
  2. **环境变量**：从环境变量读取（`FEISHU_WEBHOOK_URL`, `FEISHU_APP_ID`, `FEISHU_APP_SECRET`）
  3. **原系统config.yaml**：利用直接访问方式，从原系统config.yaml读取（回退方案）
     - Webhook: `notification.feishu_webhook`
     - API: `notification.feishu_app.app_id` 和 `app_secret`
- 包含完整的错误处理

**使用场景**：
- **交易信号通知**：发送交易信号提醒
- **风险预警**：发送风险预警消息
- **市场日报**：发送每日市场分析报告
- **系统状态**：发送系统运行状态通知
- **错误告警**：发送系统错误告警

---

### 2. send_signal_alert.py - 交易信号提醒

**功能说明**：
- 发送格式化的交易信号提醒到飞书
- 融合 Coze `send_signal_alert.py` 的完整逻辑
- 支持买入、卖出、预警、风险等多种信号类型
- 使用飞书卡片消息，展示更丰富的信息

**使用方法**：
```python
from plugins.notification.send_signal_alert import tool_send_signal_alert

# 发送买入信号
result = tool_send_signal_alert(
    signal_type="buy",
    symbol="510300",
    symbol_name="沪深300ETF",
    price=4.85,
    signal_strength="strong",
    reason="MACD金叉 + 均线多头排列",
    suggestion="建议买入，止损位4.70"
)

# 发送风险预警
result = tool_send_signal_alert(
    signal_type="risk",
    symbol="510300",
    price=4.85,
    signal_strength="high",
    reason="价格接近止损位",
    suggestion="注意风险，考虑减仓"
)
```

**输入参数**：
- `signal_type` (str): 信号类型，可选值：
  - `"buy"`: 买入信号
  - `"sell"`: 卖出信号
  - `"alert"`: 预警信号
  - `"risk"`: 风险信号
- `symbol` (str): 标的代码，如 "510300"
- `symbol_name` (str, optional): 标的名称，如 "沪深300ETF"
- `price` (float): 当前价格
- `signal_strength` (str): 信号强度，可选 "strong", "medium", "weak"
- `reason` (str): 信号原因
- `suggestion` (str): 操作建议
- `webhook_url` (str, optional): 飞书Webhook地址

**输出格式**：
```python
{
    "success": True,
    "message": "Successfully sent signal alert",
    "data": {
        "symbol": "510300",
        "signal_type": "buy",
        "timestamp": "2025-01-15 14:30:00"
    }
}
```

**技术实现要点**：
- 使用飞书卡片消息格式
- 根据信号类型自动选择卡片颜色和图标
- 自动格式化价格、信号强度等信息
- 包含完整的错误处理

**使用场景**：
- **交易信号通知**：发送买入/卖出信号提醒
- **风险预警**：发送风险预警通知
- **策略提醒**：发送策略执行提醒

---

### 3. send_risk_alert.py - 风险预警

**功能说明**：
- 发送格式化的风险预警到飞书
- 融合 Coze `send_risk_alert.py` 的完整逻辑
- 支持波动率、回撤、仓位、市场等多种风险类型
- 使用飞书卡片消息，展示风险详情和处理建议

**使用方法**：
```python
from plugins.notification.send_risk_alert import tool_send_risk_alert

# 发送波动率风险预警
result = tool_send_risk_alert(
    risk_type="volatility",
    risk_level="high",
    symbol="510300",
    description="ETF波动率超过阈值",
    current_value=0.25,
    threshold=0.20,
    suggestion="建议降低仓位或设置更严格的止损"
)

# 发送回撤风险预警
result = tool_send_risk_alert(
    risk_type="drawdown",
    risk_level="critical",
    symbol="510300",
    description="账户回撤超过10%",
    current_value=0.12,
    threshold=0.10,
    suggestion="立即检查持仓，考虑止损"
)
```

**输入参数**：
- `risk_type` (str): 风险类型，可选值：
  - `"volatility"`: 波动率风险
  - `"drawdown"`: 回撤风险
  - `"position"`: 仓位风险
  - `"market"`: 市场风险
- `risk_level` (str): 风险等级，可选 "low", "medium", "high", "critical"
- `symbol` (str): 相关标的代码
- `description` (str): 风险描述
- `current_value` (float): 当前值
- `threshold` (float): 阈值
- `suggestion` (str): 处理建议
- `webhook_url` (str, optional): 飞书Webhook地址

**输出格式**：
```python
{
    "success": True,
    "message": "Successfully sent risk alert",
    "data": {
        "risk_type": "volatility",
        "risk_level": "high",
        "symbol": "510300",
        "timestamp": "2025-01-15 14:30:00"
    }
}
```

**技术实现要点**：
- 使用飞书卡片消息格式
- 根据风险等级自动选择卡片颜色（低风险：绿色，高风险：红色）
- 自动格式化数值和百分比
- 包含完整的错误处理

**使用场景**：
- **波动率预警**：波动率超过阈值时发送预警
- **回撤预警**：账户回撤超过阈值时发送预警
- **仓位预警**：仓位比例过高时发送预警
- **市场风险**：市场异常波动时发送预警

---

### 4. send_daily_report.py - 市场日报

**功能说明**：
- 发送格式化的市场日报到钉钉自定义机器人（SEC 加签）
- 融合 Coze `send_daily_report.py` 的完整逻辑
- 汇总当日市场表现、交易信号、风险状况等信息
- 展示完整的日报内容（钉钉 Markdown/文本呈现）

> 2026 版本更新：市场日报改为发送到钉钉自定义机器人（`tool_send_daily_report` 复用 SEC 加签逻辑）。

**使用方法**：
```python
from plugins.notification.send_daily_report import tool_send_daily_report

# 发送市场日报（钉钉）
result = tool_send_daily_report(
    report_data={
        "market_overview": {
            "index_change": 0.5,
            "etf_change": 0.3,
            "volume": "放大"
        },
        "signals": [
            {"type": "buy", "symbol": "510300", "strength": "strong"},
            {"type": "sell", "symbol": "510050", "strength": "medium"}
        ],
        "risk_status": {
            "level": "low",
            "description": "市场风险可控"
        }
    },
    report_date="2025-01-15"
)
```

 **输入参数**：
- `report_data` (dict): 报告数据，包含：
  - `market_overview`: 市场概览（指数涨跌幅、ETF涨跌幅、成交量等）
  - `signals`: 交易信号列表
  - `risk_status`: 风险状况
  - 其他自定义字段
- `report_date` (str, optional): 报告日期（YYYY-MM-DD），默认今天
- `webhook_url` (str, optional): 可选：钉钉自定义机器人 webhook（包含 access_token；建议主要使用 `~/.openclaw/.env` 的环境变量）

**输出格式**：
```python
{
    "success": True,
    "message": "Successfully sent daily report",
    "data": {
        "report_date": "2025-01-15",
        "timestamp": "2025-01-15 15:30:00"
    }
}
```

**技术实现要点**：
- 使用钉钉自定义机器人（SEC 加签）发送 Markdown/文本呈现
- 自动格式化市场数据、信号列表等信息
- 支持自定义报告内容
- 包含完整的错误处理

**使用场景**：
- **盘后日报**：每天收盘后发送市场日报
- **周报月报**：定期发送周报、月报
- **策略总结**：发送策略执行总结报告

---

## 数据流

```
分析插件/信号生成
    ↓
调用通知插件
    ↓
格式化消息内容
    ↓
发送到钉钉（Webhook/API）
    ↓
用户收到通知
```

## 配置方式

### 方式1：环境变量（推荐）

- `OPENCLAW_DINGTALK_CUSTOM_ROBOT_WEBHOOK_URL`: 钉钉自定义机器人 webhook（包含 `access_token`）
- `OPENCLAW_DINGTALK_CUSTOM_ROBOT_SECRET`: 钉钉“安全模式”SEC 密钥（用于 SEC 加签）
- `DINGTALK_KEYWORD`（或 `MONITOR_DINGTALK_KEYWORD`）: 关键词安全校验用（若机器人启用）

### 方式2：可选回退（keyword）

如果你的钉钉机器人启用了「关键词安全校验」，但你没有显式传入 `keyword`：
- 可把 `keyword` 写入 `~/.openclaw/workspaces/shared/alert_webhook.json`（tool 内部会尽量读取）

## 依赖包

- `requests`: HTTP 请求

## 注意事项

1. **Webhook vs API**：优先使用 Webhook，配置简单；API 方式需要应用凭证
2. **消息格式**：确保消息内容格式正确，特别是富文本和卡片消息
3. **频率限制**：注意钉钉 API 的频率限制，避免频繁发送
4. **错误处理**：包含完整的错误处理，失败时会返回错误信息
5. **安全性**：API Key 和 Webhook URL 应妥善保管，不要泄露

## 迁移说明

- 通知逻辑融合了 Coze 插件的完整功能
- 支持 Webhook 和 API 两种方式，灵活配置
- 支持多种消息类型，满足不同通知需求
- 插件设计保持独立性，易于扩展其他通知渠道