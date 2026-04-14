# 每日市场分析报告 — 网上对标与验收

**用途**：为「etf: 每日市场分析报告」（约 **工作日 16:30**，`workflows/daily_market_report.yaml`）提供 **章节结构** 参考。对标对象是 **网上公开的交易日收盘复盘 / 当日市场综述**，**不是** 9:15 早盘采集、**不是** 9:28 开盘晨报正文。

**产品定位（任务级，与仓库 README 一致）**：本系统为 **A 股、宽基 ETF 及（可选）期权/期指交易助手**；本任务产出是 **以 A 股与宽基 ETF 为主线的每日市场分析**，章节应对齐「收盘复盘 / 当日综述」体例。**期权、Greeks、单日波动区间等多为延伸维度**，除非当日工具结果明确侧重期权，否则**不应**把全文写成「单一标的期权简报」或让读者误以为产品仅服务期权。

**dual evidence**：演化或人工改版时，请在 PR/复盘 中同时给出 `[LOCAL_EVIDENCE]`（一次完整 Agent 运行日志或 `report_data` 快照路径）与 `[EXTERNAL_REFS]`（下表至少一条可访问 URL）。

---

## 1. 典型章节（归纳用）

以下为常见「收盘点评」类结构，可按来源微调；正文数据须来自工具或标注 `numeric_unverified`。

| 章节 | 说明 |
|------|------|
| 大盘与量能 | **主要指数涨跌**、**成交额/量能对比**（与网上收评「全市场概况」同位）。**本仓库约定**：合并后配置 `data_cache.index_codes` 所涉**重要指数**一律在本节呈现（来源：`config/domains/reference.yaml`），**不单列「指数一览」或等价重复节**；量能/两市成交额等缺口须标出。 |
| **主要 ETF 及预警股票池** | 本仓库增项（网上通用表常不单独成节，此处**显式列入章节**以便分段与验收）。正文为 **主要 ETF + 预警/监控股票** 当日一览：`data_cache.etf_codes`、`stock_codes` 与 `signal_generation.stock.watchlist` 等**并集**；各标的涨跌/量能或一句概览；**不含**指数重复段（指数见上一行「大盘与量能」）。钉钉 Markdown 建议标题：`## 主要 ETF 及预警股票池`（与 plan 维度「核心池与预警标的当日一览」对应）。 |
| 板块与题材 | 领涨领跌、持续性简述 |
| 资金 | 北向等（注意 T 日/T-1 口径） |
| 要闻与政策 | 精简列表，避免标题党 |
| 外围与大宗 | 亚欧优先，美股可作昨夜背景 |
| 展望与风险 | 情景化表述，非具体买卖指令 |

**与 Cursor plan《每日市场分析报告优化》§2.2–2.3 的对应**：上表已将 **「主要 ETF 及预警股票池」** 列为独立章节行；plan 中维度名「核心池与预警标的当日一览」与此为同一节。另可含 **结构与主线**、**波动与关键位**、**信号与纪律** 等散户向小节，详见该 plan 维度表。

---

## 2. 外部样例（[EXTERNAL_REFS] · 结构参考）

以下为「交易日收盘复盘 / 收评」类公开页面，用于**章节结构**对标；指数与个股数据以本系统工具为准，勿直接抄录下文链接中的行情数值作实盘依据。

**文档收录日（本表写入仓库）**：2026-03-29（UTC+8）。链接有效性以各站点为准；若失效请替换为同站同类「收评/复盘」新稿并更新本表。

| # | 来源类型 | URL | 抓取/收录日期（UTC+8） | 备注 |
|---|----------|-----|------------------------|------|
| 1 | 东方财富财富号 · 收评 | https://caifuhao.eastmoney.com/news/20260311152120952354990 | 2026-03-29 | 文章日期约 2026-03-11；标题含「A股收盘点评」 |
| 2 | 东方财富财富号 · 复盘 | https://caifuhao.eastmoney.com/news/20260325191528340871320 | 2026-03-29 | 文章日期约 2026-03-25；「市场复盘报告」体例 |
| 3 | 东方财富财富号 · 收评 | https://caifuhao.eastmoney.com/news/20260323151248287191170 | 2026-03-29 | 文章日期约 2026-03-23；「A股收评（完整版）」 |
| 4 | 上海证券报 · 电子版收评 | https://paper.cnstock.com/html/2026-03/25/content_2191971.htm | 2026-03-29 | 文章日期 2026-03-25；大势/板块综述 |
| 5 | 上海证券报 · 电子版收评 | https://paper.cnstock.com/html/2026-03/26/content_2192254.htm | 2026-03-29 | 文章日期 2026-03-26；指数与全市场概况 |

**补充（频道级，非单篇）**：财联社「看盘」入口 https://www.cls.cn/finance — 用于观察同类站点**栏目**如何组织盘面/收评（可随首页改版调整书签，不必写入上表逐条验收）。

---

## 3. Evolver / 自动演化边界

- **允许**：`plugins/analysis/**`、`strategies/**`、`docs/research/**`、部分 `docs/openclaw/**`、`workflows/*.yaml`（与 `config/evolver_scope.yaml` 一致时）。
- **禁止自动修改**：`plugins/notification/**`（含 `send_daily_report.py`）、`plugins/data_collection/**`、带密钥的 `config/openclaw_*.yaml` 等；展示层变更走 **人工 PR**。
- **`AUTOFIX_ALLOWED=false`（合并前必标）**：凡修改 `plugins/notification/**`（含钉钉长文、标题、章节、`_format_daily_report` / `tool_send_daily_report` 等）的 PR，**须在 PR 描述或首条评论中显式写明** `AUTOFIX_ALLOWED=false`，与 Evolver/自动演化门禁及上文「禁止自动修改」一致，避免被误当可自动合并项。

---

## 4. 验收清单（VERIFY）

- [ ] `daily_market_report.yaml` 的 `schedule` 与 `~/.openclaw/cron/jobs.json` 中该任务 **expr** 一致（均为 **16:30 工作日** 意图）。
- [ ] 一次完整运行日志中，`tool_analyze_after_close` 或后续步骤曾尝试可选工具；失败处有「警告」而非任务 **error**。
- [ ] 终稿含免责声明；无具体下单指令。
- [ ] **大盘与量能**：含主要指数涨跌与成交额/量能对比（或显式缺口说明）；**重要指数**已在本节消化，**无**与「**主要 ETF 及预警股票池**」节重复的单独指数块。
- [ ] **主要 ETF 及预警股票池**（若已启用新版式）：终稿含对应 Markdown 章节标题（建议 `## 主要 ETF 及预警股票池`）；仅 ETF + 预警股类内容，**指数不重述**；缺数据时有 `*_error` 或短说明。
- [ ] **P0 数据与版式**：工作流在发送前已尽量合并 `tool_sector_heat_score`、`tool_fetch_northbound_flow`、`tool_compute_index_key_levels`（300+905）、政策/行业/公告摘要工具、`tool_fetch_macro_commodities` 等；`tool_analyze_after_close_and_send_daily_report` 或 `report_type=daily_market` 终稿含「执行摘要」「结构与主线」「信息面」「外围与大宗」「波动与关键位」「信号与纪律」「展望与风险」等收评章节（见 `workflows/daily_market_report.yaml`）。

---

## 5. P2：分段投递与 `report_data` 契约（可选）

钉钉单条长度有限时，可在 **人工评估** 后使用 `tool_send_daily_report(..., split_markdown_sections=true)`（实现见 `plugins/notification/send_daily_report.py`），由通知层按章节拆条。**Evolver 默认不自动改** `send_daily_report.py`；若调整分段规则，走单独 PR 并标注 `AUTOFIX_ALLOWED=false`。

建议在 `report_data` / `extra_report_data` 中显式放入与网上复盘及 plan §2.2 对齐的块，便于渲染与分段，例如：`analysis`、`market_overview`、`global_index_spot` / `macro_commodities`、`northbound`、`policy_news`、`industry_news`、`key_levels`（或 `daily_report_overlay` 子集）、`llm_summary`；**大盘与量能**侧可含 `index_board_snapshot` 或与 overlay 合并的指数摘要；**主要 ETF 及预警股票池**节侧可用 `universe_price_snapshot`（**仅** ETF+股票并集，与 §1「指数归入大盘」分工一致，键名以实施为准）；启用 `split_markdown_sections=true` 时，`## 主要 ETF 及预警股票池` 应作为可识别分段锚点之一。
