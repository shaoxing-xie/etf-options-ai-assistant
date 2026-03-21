# MEMORY.md - 持久记忆与交易规则

供 memory flush 与 memory search 使用。Agent 在会话压缩前会参考此处与 dated 记忆文件，请保持更新。

**记忆双轨**：**Mem0** 对话记忆自动捕获与召回（`memory_search`）；**QMD** 本文件与 memory/*.md、workspace 文档（`qmd search` / `qmd vsearch`）。

---

## 交易与通知

- 通知渠道：飞书、钉钉群聊。
- 常用标的、阈值与工作流等可在本文件或 workspace 中按需补充。

## 工具状态

| 工具 | 状态 | 备注 |
|------|------|------|
| tool_fetch_futures_snapshot（国内） | ✅ | 东方财富数据源 |
| tool_fetch_futures_snapshot（国际） | ❌ | Yahoo Finance 受限，需配代理 |
| option_trader | ✅ | 需实盘配置 |
| tool_fetch_etf/index_realtime | ✅ | 正常 |
| tool_fetch_option_greeks | ✅ | 正常 |
| tool_fetch_index_minute | ⚠️ | 多周期调用（5,15,30）部分标的返回空或跳过；单周期调用正常 |
| tool_fetch_etf_minute | ⚠️ | 510300 5分钟正常，其他ETF报错 "'NoneType' object has no attribute 'columns'"（需修复） |
| tool_fetch_*_historical | ✅ | 历史日线数据正常 |

**最近执行记录（2026-03-18）**：
- 高优先级指数（000300/399006/000905/000016）全部成功
- ETF中仅510300部分成功（5min正常，15/30min被跳过），其他均失败

## 期货数据工具澄清（2026-03-14）

**⚠️ 重要：系统期货数据能力边界**

| 类型 | 状态 | 工具/说明 |
|------|------|-----------|
| **股指期货（A50期指）** | ✅ 可用 | `tool_fetch_a50_data`（`~/.openclaw/extensions/option-trading-assistant/plugins/data_collection/futures/fetch_a50.py`） |
| **商品期货（沪金/原油/螺纹等）** | ❌ **未实现** | 系统暂无商品期货数据采集工具 |

- A50期指工具使用 AkShare 的 `futures_global_spot_em()` 和 `futures_foreign_hist()` 接口
- A50期指是**股指期货**（跟踪富时中国A50指数），**不是商品期货**
- 如需商品期货夜盘数据，用户需通过第三方平台（东财/文华/同花顺）查看

## 钉钉用户信息（私信/群内 @）

| 用户名 | open_id（钉钉） | 群聊 conversation_id | 备注 |
|--------|-----------------|----------------------|------|
| 谢富根 | `055062293235230095` | `cid0dqwayvqu94+qeoodxl1uw==` | 群内可直接回复 |
| 邬华阳 | `013334132836291153` | 同上 | |
| 姜丹灵 | `176754005922756408` | 同上 | |

> 钉钉机器人仅能在已有会话中发消息。私信需用户先与机器人建立私聊，或通过群内 @ 提醒。

## 价格预警（2026-03-13）

- 存储：`data/alerts.json`；Cron `price-alert-polling` 每 10 分钟（交易时段）。
- 通知：钉钉群内 @ 或私信（需用户已开启私聊）。
- 指令：`#预警 代码 条件 目标值`；每人最多 5 条，触发后自动取消。

## 输出规范

盘前/盘后/信号分析报告结构、表格与 emoji 规范见 **`docs/输出规范.md`**。直接回复须与 `tool_send_daily_report` 输出丰富度一致。

## 标的池配置约定（2026-03-14 重要）

**⚠️ 所有"当前系统配置的标的清单/行业ETF列表/宽基池"等问题，一律以 `config/symbols.json` 为准**

| 文件 | 作用 |
|------|------|
| `config/symbols.json` | 统一管理指数/ETF/期指/期权底层标的池及优先级 |
| `src/symbols_loader.py` | Python加载器，提供统一API |

### 分组结构
- **core**（high）：核心宽基池，盘中高频采集
- **industry_etf**（medium）：行业/主题ETF池
- **futures**（medium）：股指与商品期货
- **options_watchlist**（low）：期权底层标的关注池

### 使用规则
1. 通过 `src/symbols_loader.py` 读取，不直接手写JSON解析
2. 回答必须说明标的池来源（config/symbols.json + 分组名）
3. 不允许再写死静态文案（如"行业ETF 0 未配置"）
4. 更新标的需给出变更前vs变更后对比，建议更新 symbols.json

---
_记忆已于 2026-03-07 重置；输出规范于 2026-03-10 更新并外迁至 docs/输出规范.md；工具状态于 2026-03-14 更新。_
